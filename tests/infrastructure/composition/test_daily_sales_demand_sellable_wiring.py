from __future__ import annotations

from uuid import uuid4

from pydantic import SecretStr
from tests.application.inventory_reconciliation.sellable_fakes import (
    MappingSellableProductCodeCatalog,
)
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.application.inventory_reconciliation.create_daily_sales_demands import (
    CreateDailySalesDemands,
)
from src.config.daily_sales_demand import DailySalesDemandSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.moysklad import MoySkladSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.daily_sales_demand import (
    build_daily_sales_demand_handler,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


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


def test_build_daily_handler_uses_sellable_catalog() -> None:
    org = uuid4()
    project = uuid4()
    agent = uuid4()
    snack_ch = uuid4()
    settings = Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
        daily_sales_demand=DailySalesDemandSettings.model_construct(
            worker_enabled=True,
            cron_hour=4,
        ),
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Europe/Moscow",
        ),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("token"),
            organization_id=str(org),
            project_id=str(project),
            demand_agent_id=str(agent),
            snack_sales_channel_id=str(snack_ch),
        ),
    )
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    handler = build_daily_sales_demand_handler(
        settings,
        machine_sales_store=InMemoryMachineSalesStore(),
        moysklad_client=FakeMoySkladClient(),
        sellable_catalog=catalog,
        client=None,
    )
    assert handler is not None
    assert isinstance(handler.create_demands, CreateDailySalesDemands)
    assert handler.create_demands.sellable_catalog is catalog
