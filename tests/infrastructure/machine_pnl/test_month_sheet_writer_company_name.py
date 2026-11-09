from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mongomock
import pytest
from pydantic import SecretStr

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
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
from src.infrastructure.composition.wiring import wire_machine_pnl_month_worker as wire_mod
from src.infrastructure.machine_pnl.memory import InMemoryPeriodPnlStore
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.machine_pnl.month_sheet_export_writer import MonthPnlSheetExportWriter
from src.infrastructure.memory import InMemoryEventStore
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


def _seed_company_store() -> InMemoryCompanyStore:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=42,
            name="Орлов М.О.",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=42,
                    roles=(KitPlatformRole.SALES_POLL,),
                ),
            ),
        ),
    )
    return store


def _stub_wire_heavy_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wire_mod,
        "warm_up_reference_data_provider",
        lambda *, provider, store, sync: None,
    )
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
            lambda cls, settings, *, client=None: wire_mod._InMemoryWorkerStatusRepository(),
        ),
    )


def _enabled_worker_settings(*, accounts_path: Path) -> Settings:
    return Settings.model_construct(
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


def test_company_name_lookup_from_directory_not_accounts_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text(
        json.dumps(
            [
                {
                    "company_id": 42,
                    "login": "legacy-user",
                    "password": "legacy-secret",
                    "name": "Wrong From JSON",
                },
            ],
        ),
        encoding="utf-8",
    )

    store = _seed_company_store()
    captured_writers: list[MonthPnlSheetExportWriter] = []
    accounts_reads: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.resolve() == accounts_path.resolve():
            accounts_reads.append(self)
        return original_read_text(self, *args, **kwargs)

    original_build = wire_mod._build_month_sheet_writer

    def capture_build(
        settings: Settings,
        *,
        timezone: object,
        provider: object,
        company_directory: object,
    ) -> MonthPnlSheetExportWriter:
        writer = original_build(
            settings,
            timezone=timezone,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            company_directory=company_directory,  # type: ignore[arg-type]
        )
        captured_writers.append(writer)
        return writer

    _stub_wire_heavy_deps(monkeypatch)
    monkeypatch.setattr(
        wire_mod,
        "build_company_store",
        lambda settings, *, mongo_client=None: store,
    )
    monkeypatch.setattr(wire_mod, "_build_month_sheet_writer", capture_build)
    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    settings = _enabled_worker_settings(accounts_path=accounts_path)
    persistence = PersistenceBundle(
        mongo_client=mongomock.MongoClient(),
        redis_client=None,
    )

    wire_mod.wire_machine_pnl_month_worker(settings, persistence=persistence)

    assert accounts_reads == []
    assert len(captured_writers) == 1
    lookup = captured_writers[0].company_name_lookup
    assert lookup is not None
    assert lookup(42) == "Орлов М.О."
    assert lookup(999) == ""
