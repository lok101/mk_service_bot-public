from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import SecretStr

from src.config.daily_sales_demand import DailySalesDemandSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle


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
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Europe/Moscow",
        ),
        daily_sales_demand=DailySalesDemandSettings.model_construct(
            worker_enabled=False,
            cron_hour=4,
        ),
        mongodb=MongoSettings.model_construct(uri=None),
    )


def test_wire_daily_sales_demand_worker_disabled_smoke() -> None:
    from src.infrastructure.composition.wiring.wire_daily_sales_demand_worker import (
        wire_daily_sales_demand_worker,
    )

    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    container = wire_daily_sales_demand_worker(
        _disabled_worker_settings(),
        persistence=persistence,
    )
    assert container.runtime.enabled is False
    assert container.outbox_processors is None
    container.close()


def test_assemble_calls_validate_when_enabled() -> None:
    from src.infrastructure.composition.wiring.assemble_daily_sales_demand_worker import (
        assemble_daily_sales_demand_worker,
    )

    settings = Settings.model_construct(
        environment="prod",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Europe/Moscow",
        ),
        daily_sales_demand=DailySalesDemandSettings.model_construct(
            worker_enabled=True,
            cron_hour=4,
        ),
        mongodb=MongoSettings.model_construct(uri="mongodb://localhost:27017/test"),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("token"),
            organization_id=str(uuid4()),
            project_id=str(uuid4()),
            demand_agent_id=str(uuid4()),
            snack_sales_channel_id="",
        ),
    )
    with pytest.raises(ValueError, match="MOYSKLAD_SNACK_SALES_CHANNEL_ID"):
        assemble_daily_sales_demand_worker(settings)


def test_daily_sales_demand_worker_container_no_app_runtime() -> None:
    from src.infrastructure.composition.daily_sales_demand_worker_container import (
        DailySalesDemandWorkerContainer,
    )
    from src.infrastructure.daily_sales_demand.worker_runtime import (
        DailySalesDemandWorkerRuntime,
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
            return "2026-08-10T00:00:00Z"

    runtime = DailySalesDemandWorkerRuntime(
        enabled=False,
        status_repository=_Status(),
        scheduler=_Scheduler(),
        clock=_Clock(),
    )
    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    container = DailySalesDemandWorkerContainer(runtime=runtime, persistence=persistence)

    assert hasattr(container, "run")
    assert hasattr(container, "close")
    assert not hasattr(container, "api_app")
    assert not hasattr(container, "dispatcher")
    field_names = set(container.__dataclass_fields__)
    assert "runtime" in field_names
    assert "persistence" in field_names
    assert "api_app" not in field_names
