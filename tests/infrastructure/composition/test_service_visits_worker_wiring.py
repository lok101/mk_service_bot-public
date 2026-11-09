from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.mongodb import MongoSettings
from src.config.redis import RedisSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.service_visits import ServiceVisitsSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.wiring.assemble_service_visits_worker import (
    assemble_service_visits_worker,
)


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


def test_disabled_worker_assemble_skips_mongo_uri() -> None:
    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Asia/Yekaterinburg",
            service_day_end_hour=6,
        ),
        service_visits=ServiceVisitsSettings.model_construct(worker_enabled=False),
        mongodb=MongoSettings.model_construct(uri=None),
        redis=RedisSettings.model_construct(uri=None),
    )
    assemble_service_visits_worker(settings)


def test_enabled_worker_assemble_requires_mongo_uri() -> None:
    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Asia/Yekaterinburg",
            service_day_end_hour=6,
        ),
        service_visits=ServiceVisitsSettings.model_construct(worker_enabled=True),
        mongodb=MongoSettings.model_construct(uri=None),
        redis=RedisSettings.model_construct(uri=None),
    )
    with pytest.raises(ValueError, match="MONGODB_URI must be set"):
        assemble_service_visits_worker(settings)
