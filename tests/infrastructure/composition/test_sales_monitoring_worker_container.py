from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import mongomock
import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.mongodb import MongoSettings
from src.config.sales_monitoring import SalesMonitoringSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.sales_monitoring.worker_runtime import SalesMonitoringWorkerRuntime


def _stub_forms() -> GoogleFormsSettings:
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


def _disabled_worker_settings() -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        sales_monitoring=SalesMonitoringSettings.model_construct(worker_enabled=False),
        mongodb=MongoSettings.model_construct(uri=None),
    )


def _enabled_worker_settings(*, accounts_path: Path) -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="",
            coffee_technician_locations_spreadsheet_id="",
            technicians_directory_spreadsheet_id="ss-tech-dir",
            technicians_directory_sheet_id=7,
        ),
        kitvending=KitVendingSettings.model_construct(
            accounts_path=accounts_path,
            requests_per_window=1,
            window_seconds=10.0,
            backoff_seconds=60.0,
        ),
        sales_monitoring=SalesMonitoringSettings.model_construct(
            worker_enabled=True,
            telegram_bot_token=SecretStr("report-bot-token"),
            telegram_chat_id=-1001,
            decline_telegram_chat_id=-1003,
            alert_telegram_chat_id=-1002,
            alert_telegram_bot_token=None,
            tz="Asia/Yekaterinburg",
            days_for_average=28,
            sales_drop_percent=30,
            last_sale_lookup_days=28,
            baseline_min_points=4,
            baseline_winsorize_min_points=8,
            baseline_winsorize_percent=10,
            no_sales_habitual_max_nonempty=1,
            offline_ping_threshold_minutes=25,
            offline_poll_interval_minutes=60,
            offline_poll_from_hour=8,
            offline_poll_to_hour=22,
            excluded_machine_codes=(),
            report_compare_cron="0 8 * * *",
            report_today_cron="0 15 * * *",
        ),
        mongodb=MongoSettings.model_construct(
            uri="mongodb://localhost:27017",
            database="test",
            sales_monitoring_worker_status_collection="sales_monitoring_worker_status",
            sales_monitoring_audit_collection="sales_monitoring_audit",
            outbox_collection="outbox",
            events_collection="machine_events",
            machine_sales_collection="machine_sales",
            reference_data_snapshots_collection="reference_data_snapshots",
            outbox_poll_interval_seconds=1.0,
        ),
    )


class _Status:
    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        return None


class _Scheduler:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _Clock:
    def now_utc_iso(self) -> str:
        return "2026-07-29T00:00:00Z"


def _runtime(*, enabled: bool = False) -> SalesMonitoringWorkerRuntime:
    return SalesMonitoringWorkerRuntime(
        enabled=enabled,
        status_repository=_Status(),
        scheduler=_Scheduler(),
        clock=_Clock(),
    )


def test_sales_monitoring_worker_container_does_not_assemble_app_runtime() -> None:
    from src.infrastructure.composition.sales_monitoring_worker_container import (
        SalesMonitoringWorkerContainer,
    )

    runtime = _runtime()
    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    container = SalesMonitoringWorkerContainer(runtime=runtime, persistence=persistence)

    assert hasattr(container, "run")
    assert hasattr(container, "close")
    assert not hasattr(container, "api_app")
    assert not hasattr(container, "dispatcher")
    assert not hasattr(container, "bot")
    field_names = set(container.__dataclass_fields__)
    assert "runtime" in field_names
    assert "persistence" in field_names
    assert "api_app" not in field_names


def test_wire_sales_monitoring_worker_disabled_smoke() -> None:
    from src.infrastructure.composition.wiring.wire_sales_monitoring_worker import (
        wire_sales_monitoring_worker,
    )

    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    container = wire_sales_monitoring_worker(
        _disabled_worker_settings(),
        persistence=persistence,
    )
    assert container.runtime is not None
    assert callable(container.close)
    container.close()


def test_assemble_calls_validate_when_building() -> None:
    from src.infrastructure.composition.wiring.assemble_sales_monitoring_worker import (
        assemble_sales_monitoring_worker,
    )

    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        sales_monitoring=SalesMonitoringSettings.model_construct(
            worker_enabled=True,
            telegram_bot_token=SecretStr("report-bot-token"),
            telegram_chat_id=-1001,
            decline_telegram_chat_id=-1003,
            alert_telegram_chat_id=-1002,
        ),
        mongodb=MongoSettings.model_construct(uri=None),
    )
    with pytest.raises(ValueError, match="MONGODB_URI"):
        assemble_sales_monitoring_worker(settings)


def test_worker_registers_sales_monitoring_audit_handler_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Production `_build_enabled_job_bundle` registers audit; stub only Mongo/kit deps."""
    from src.application.outbox.handler_ids import SALES_MONITORING_AUDIT_HANDLER_ID
    from src.application.service_visits.memory import InMemoryServiceVisitStore
    from src.infrastructure.composition.sales_monitoring_worker_container import (
        SalesMonitoringWorkerContainer,
    )
    from src.infrastructure.composition.wiring import wire_sales_monitoring_worker as wire_mod
    from src.infrastructure.machine_operations.maintenance_cooldown_bypass_memory import (
        NullMaintenanceCooldownBypassReader,
    )
    from src.infrastructure.memory import InMemoryEventStore
    from src.infrastructure.outbox import InMemoryOutboxStore
    from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore
    from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore
    from src.infrastructure.sales_monitoring.memory_status_board import (
        InMemoryStatusBoardPointerStore,
    )
    from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text(
        json.dumps(
            [
                {
                    "login": "head",
                    "password": "secret",
                    "company_id": 1,
                    "name": "head",
                }
            ]
        ),
        encoding="utf-8",
    )
    settings = _enabled_worker_settings(accounts_path=accounts_path)
    mongo_client: Any = mongomock.MongoClient()
    persistence = PersistenceBundle(mongo_client=mongo_client, redis_client=None)

    monkeypatch.setattr(
        wire_mod,
        "build_outbox_store",
        lambda settings, client=None: InMemoryOutboxStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_sales_monitoring_audit_store",
        lambda settings, client=None: InMemorySalesMonitoringAuditStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_status_board_pointer_store",
        lambda settings, client=None: InMemoryStatusBoardPointerStore(),
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
        "build_reference_data_snapshot_store",
        lambda settings, client=None: InMemoryReferenceDataSnapshotStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_service_visit_store",
        lambda settings, client=None: InMemoryServiceVisitStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_maintenance_cooldown_bypass_reader",
        lambda settings, client=None: NullMaintenanceCooldownBypassReader(),
    )
    monkeypatch.setattr(
        wire_mod.MongoSalesMonitoringWorkerStatusRepository,
        "from_settings",
        classmethod(
            lambda cls, settings, *, client=None: wire_mod._InMemoryWorkerStatusRepository()
        ),
    )

    def fake_kit_reader(
        settings: Settings,
        *,
        mongo_client: object,
        http_client: object,
    ) -> tuple[object, tuple[Any, ...]]:
        del settings, mongo_client

        class _FakeKitStates:
            def statuses_for(self, **_kwargs: object) -> tuple[object, ...]:
                return ()

        closer = getattr(http_client, "close", lambda: None)
        return _FakeKitStates(), (closer,)

    monkeypatch.setattr(wire_mod, "_build_head_kit_states_reader", fake_kit_reader)

    container = wire_mod.wire_sales_monitoring_worker(settings, persistence=persistence)

    assert isinstance(container, SalesMonitoringWorkerContainer)
    assert container.runtime.enabled is True
    assert container.outbox_processors is not None
    assert container.outbox_processors.is_registered(SALES_MONITORING_AUDIT_HANDLER_ID)
    container.close()


def test_wire_sm_enabled_requires_technicians_directory(tmp_path: Path) -> None:
    from src.infrastructure.composition.wiring.wire_sales_monitoring_worker import (
        wire_sales_monitoring_worker,
    )

    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text("[]", encoding="utf-8")
    base = _enabled_worker_settings(accounts_path=accounts_path)
    settings = Settings.model_construct(
        environment=base.environment,
        telegram=base.telegram,
        google_forms=base.google_forms,
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="",
            coffee_technician_locations_spreadsheet_id="",
            technicians_directory_spreadsheet_id="",
            technicians_directory_sheet_id=None,
        ),
        kitvending=base.kitvending,
        sales_monitoring=base.sales_monitoring,
        mongodb=base.mongodb,
    )
    persistence = PersistenceBundle(
        mongo_client=mongomock.MongoClient(),
        redis_client=None,
    )

    with pytest.raises(ValueError, match="TECHNICIANS_DIRECTORY"):
        wire_sales_monitoring_worker(settings, persistence=persistence)


def test_entrypoint_boots_sales_monitoring_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_sales_monitoring_worker

    from src.infrastructure.composition.sales_monitoring_worker_container import (
        SalesMonitoringWorkerContainer,
    )

    calls: list[str] = []
    fake_runtime = _runtime()
    fake_persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    built = SalesMonitoringWorkerContainer(
        runtime=fake_runtime,
        persistence=fake_persistence,
    )

    async def fake_run(self: SalesMonitoringWorkerContainer) -> None:
        calls.append("run")

    def fake_from_settings(
        cls: type[SalesMonitoringWorkerContainer],
        settings: Settings | None = None,
    ) -> SalesMonitoringWorkerContainer:
        calls.append("from_settings")
        assert settings is not None
        return built

    def fake_close(self: SalesMonitoringWorkerContainer) -> None:
        calls.append("close")

    monkeypatch.setattr(
        run_sales_monitoring_worker.SalesMonitoringWorkerContainer,
        "from_settings",
        classmethod(fake_from_settings),
    )
    monkeypatch.setattr(run_sales_monitoring_worker.SalesMonitoringWorkerContainer, "run", fake_run)
    monkeypatch.setattr(
        run_sales_monitoring_worker.SalesMonitoringWorkerContainer,
        "close",
        fake_close,
    )
    monkeypatch.setattr(
        run_sales_monitoring_worker,
        "get_settings",
        _disabled_worker_settings,
    )
    monkeypatch.setattr(
        run_sales_monitoring_worker,
        "configure_ops_alert_logging",
        lambda settings: MagicMock(stop=lambda: calls.append("ops_stop")),
    )

    asyncio.run(run_sales_monitoring_worker.main())
    assert calls == ["from_settings", "run", "close", "ops_stop"]
