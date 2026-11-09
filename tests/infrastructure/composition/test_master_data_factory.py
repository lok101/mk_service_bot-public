from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import mongomock
import pytest
from pydantic import SecretStr

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.machine_pnl_month import MachinePnlMonthSettings
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories.master_data import (
    attach_master_data,
    build_master_data_stores,
)
from src.infrastructure.machine_pnl.memory import InMemoryPeriodPnlStore
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.memory import InMemoryEventStore
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "test-revision-secret")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "test-loading-secret")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "https://forms.example/warehouse",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "test-warehouse-inventory-secret",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        "entry.3",
    )
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_factory_memory_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    stores = build_master_data_stores(settings, mongo_client=None)
    assert isinstance(stores, InMemoryMasterDataStores)
    assert stores.locations.is_empty() is True


def test_attach_master_data_hydrates_when_enabled() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="A",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    provider = ReferenceDataProvider()
    attach_master_data(provider, stores=stores, enabled=True)
    assert provider.locations_catalog_or_none() is not None


def test_attach_master_data_noop_when_disabled() -> None:
    provider = ReferenceDataProvider()
    attach_master_data(
        provider,
        stores=InMemoryMasterDataStores(),
        enabled=False,
    )
    assert provider.locations_catalog_or_none() is None


def test_wire_machine_pnl_month_worker_attaches_master_data_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Happy: MASTER_DATA_ENABLED + stores → park/directory hydrate at wire and re-warm."""
    from src.infrastructure.composition.wiring import wire_machine_pnl_month_worker as wire_mod

    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="A",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )

    captured: list[ReferenceDataProvider] = []
    attach_calls: list[bool] = []

    def fake_warm_up(
        *,
        provider: ReferenceDataProvider,
        store: object,
        sync: object,
    ) -> None:
        del store, sync
        captured.append(provider)

    def tracking_attach(
        provider: ReferenceDataProvider,
        *,
        stores: InMemoryMasterDataStores,
        enabled: bool,
    ) -> None:
        attach_calls.append(enabled)
        attach_master_data(provider, stores=stores, enabled=enabled)

    monkeypatch.setattr(wire_mod, "warm_up_reference_data_provider", fake_warm_up)
    monkeypatch.setattr(
        wire_mod,
        "build_master_data_stores",
        lambda settings, mongo_client=None: stores,
        raising=False,
    )
    monkeypatch.setattr(wire_mod, "attach_master_data", tracking_attach, raising=False)
    monkeypatch.setattr(
        wire_mod,
        "build_reference_data_snapshot_store",
        lambda settings, client=None: InMemoryReferenceDataSnapshotStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_reference_data_sync",
        lambda settings, store, provider: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_event_store",
        lambda settings, client=None: InMemoryEventStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_machine_sales_store",
        lambda settings, client=None: InMemoryMachineSalesStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_period_pnl_store",
        lambda settings, client=None: InMemoryPeriodPnlStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_month_pnl_snapshot_store",
        lambda settings, client=None: InMemoryMonthPnlSnapshotStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_period_reconciliation_repository",
        lambda settings, client=None: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_coffee_recipe_repository",
        lambda settings, client=None: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_machine_company_occupancy_store",
        lambda settings, client=None: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_unit_cost_catalog_loader",
        lambda settings: lambda: (),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_opex_params_loader",
        lambda settings: lambda: (),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_location_rent_loader",
        lambda settings: lambda: (),
    )
    monkeypatch.setattr(
        wire_mod,
        "_build_month_sheet_writer",
        lambda settings, *, timezone, provider, company_directory=None: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "ComputeMonthPnlSnapshot",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "as_period_snapshot_reader",
        lambda repo: repo,
    )
    monkeypatch.setattr(
        wire_mod,
        "run_machine_pnl_month_tick",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        wire_mod.MongoMachinePnlMonthWorkerStatusRepository,
        "from_settings",
        classmethod(
            lambda cls, settings, *, client=None: wire_mod._InMemoryWorkerStatusRepository()
        ),
    )

    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    accounts_path = tmp_path / "kit_platform_accounts.json"
    write_platform_accounts_file(accounts_path, platform_account_row(company_id=123))
    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=GoogleFormsSettings.model_construct(
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
        ),
        machine_pnl_month=MachinePnlMonthSettings.model_construct(
            enabled=True,
            worker_enabled=True,
            sheet_spreadsheet_id="ss",
            sheet_id=1,
            ratio_lookback_periods=3,
            worker_interval_hours=24,
        ),
        master_data=MasterDataSettings.model_construct(
            enabled=True,
            session_secret=SecretStr("session-secret"),
            telegram_bot_username="mk_bot",
            sheets_export_enabled=False,
        ),
        mongodb=MongoSettings.model_construct(
            uri="mongodb://localhost:27017",
            database="test",
        ),
        google_sheets=GoogleSheetsSettings.model_construct(credentials_file=""),
        kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Asia/Yekaterinburg",
            service_day_end_hour=6,
        ),
    )
    persistence = PersistenceBundle(
        mongo_client=mongomock.MongoClient(),
        redis_client=None,
    )

    container = wire_mod.wire_machine_pnl_month_worker(settings, persistence=persistence)

    assert attach_calls == [True]
    assert captured
    assert captured[0].locations_catalog_or_none() is not None
    assert captured[0].locations_directory_or_none() is not None

    container.runtime.scheduler.callback()
    assert attach_calls == [True, True]
