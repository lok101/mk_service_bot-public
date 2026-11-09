from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings


def _google_forms_stub() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("test-webhook-secret"),
        revision_form_token_secret=SecretStr("test-revision-secret"),
        loading_form_token_secret=SecretStr("test-loading-secret"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "test-warehouse-inventory-secret",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _complete_matrix_runtime_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    worker_enabled: bool = True,
    **updates: object,
) -> Settings:
    accounts_path = tmp_path / "kit_platform_accounts.json"
    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    write_platform_accounts_file(accounts_path, platform_account_row())
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(
        "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE",
        str(credentials_path),
    )
    base = Settings.model_construct(
        google_forms=_google_forms_stub(),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file=str(credentials_path),
        ),
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=worker_enabled,
            google_sheets_spreadsheet_id="sheet-id",
            product_multipliers_sheet_id=3,
        ),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("ms-token"),
            main_store_id="11111111-1111-1111-1111-111111111111",
        ),
        kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=12345,
        ),
    )
    if not updates:
        return base
    return base.model_copy(update=updates)


def _worker_settings(**updates: object) -> Settings:
    base = Settings.model_construct(
        google_forms=_google_forms_stub(),
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=True,
            google_sheets_spreadsheet_id="sheet-id",
            product_multipliers_sheet_id=3,
        ),
        moysklad=MoySkladSettings.model_construct(api_token=None),
        kitvending=KitVendingSettings.model_construct(
            accounts_path=Path("/nonexistent/kitvending_accounts.json"),
        ),
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
    )
    if not updates:
        return base
    return base.model_copy(update=updates)


def _complete_seed_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    worker_enabled: bool = False,
    **updates: object,
) -> Settings:
    return _complete_matrix_runtime_settings(
        tmp_path,
        monkeypatch,
        worker_enabled=worker_enabled,
        **updates,
    )
