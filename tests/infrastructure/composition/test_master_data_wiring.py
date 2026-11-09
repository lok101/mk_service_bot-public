from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from src.application.master_data import InMemoryMasterDataStores, InstallMachineAtLocation
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.master_data import build_master_data_stores


def _google_forms() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("dev-webhook-secret"),
        revision_form_token_secret=SecretStr("dev-revision-secret"),
        loading_form_token_secret=SecretStr("dev-loading-secret"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "dev-warehouse-inventory-secret",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _settings_without_mongo(tmp_path: Path) -> Settings:
    """Как `tests/scripts/test_matrix_admin.py::_settings_without_mongo`."""
    accounts = tmp_path / "kit_platform_accounts.json"
    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    write_platform_accounts_file(accounts, platform_account_row(company_id=1, kit_company_id=1))
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=42,
        ),
        google_forms=_google_forms(),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file=str(credentials),
        ),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("ms-token"),
            main_store_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ),
        kitvending=KitVendingSettings.model_construct(accounts_path=accounts),
        mongodb=MongoSettings.model_construct(uri=None),
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=False,
            google_sheets_spreadsheet_id="sheet-id",
            product_multipliers_sheet_id=3,
        ),
    )


def test_runtime_wires_master_data_stores_from_master_data_package(
    tmp_path: Path,
) -> None:
    stores = build_master_data_stores(_settings_without_mongo(tmp_path))
    assert isinstance(stores, InMemoryMasterDataStores)
    assert InstallMachineAtLocation is not None


_COMMAND_SIDE = (
    "MasterDataStores",
    "MasterMachineStore",
    "MasterLocationStore",
    "MasterPlacementStore",
    "SystemUserStore",
    "TechnicianStore",
    "run_master_data_sheets_export",
    "machine_ids_excluded_from_no_sales_monitoring",
)


def test_composition_imports_command_side_from_master_data_not_reference_data() -> None:
    root = Path("src/infrastructure/composition")
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for block_prefix in (
            "from src.application.reference_data import",
            "from src.application.reference_data.ports import",
        ):
            if block_prefix not in text:
                continue
            start = text.index(block_prefix)
            chunk = text[start : start + 800]
            for name in _COMMAND_SIDE:
                if name in chunk:
                    offenders.append(f"{path.as_posix()}: {name}")
    assert offenders == []
