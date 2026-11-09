from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.config.daily_sales_demand import DailySalesDemandSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import Settings, validate_daily_sales_demand_worker_settings


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_daily_sales_demand_defaults_disabled() -> None:
    s = DailySalesDemandSettings()
    assert s.worker_enabled is False
    assert s.cron_hour == 4
    assert s.not_ready_retry_minutes == 15
    assert s.not_ready_max_attempts == 48


def test_not_ready_retry_bounds() -> None:
    DailySalesDemandSettings(not_ready_retry_minutes=1, not_ready_max_attempts=1)
    with pytest.raises(ValidationError):
        DailySalesDemandSettings(not_ready_retry_minutes=0)
    with pytest.raises(ValidationError):
        DailySalesDemandSettings(not_ready_max_attempts=0)


def test_cron_hour_bounds() -> None:
    DailySalesDemandSettings(cron_hour=0)
    DailySalesDemandSettings(cron_hour=23)
    with pytest.raises(ValidationError):
        DailySalesDemandSettings(cron_hour=-1)
    with pytest.raises(ValidationError):
        DailySalesDemandSettings(cron_hour=24)


def test_moysklad_channel_defaults_empty() -> None:
    m = MoySkladSettings()
    assert m.snack_sales_channel_id == ""
    assert not hasattr(m, "vending_coffee_sales_channel_id")


def test_mongodb_daily_status_collection_default() -> None:
    m = MongoSettings()
    assert m.daily_sales_demand_worker_status_collection == "daily_sales_demand_worker_status"


def test_disabled_skips_channel_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("DAILY_SALES_DEMAND_WORKER_ENABLED", "false")
    monkeypatch.delenv("MOYSKLAD_SNACK_SALES_CHANNEL_ID", raising=False)
    monkeypatch.delenv("MOYSKLAD_VENDING_COFFEE_SALES_CHANNEL_ID", raising=False)
    validate_daily_sales_demand_worker_settings(Settings())


def test_enabled_prod_requires_channels_and_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DAILY_SALES_DEMAND_WORKER_ENABLED", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/test")
    monkeypatch.setenv("MOYSKLAD_API_TOKEN", "token")
    monkeypatch.setenv("MOYSKLAD_ORGANIZATION_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_PROJECT_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_DEMAND_AGENT_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_SNACK_SALES_CHANNEL_ID", "")
    with pytest.raises(ValueError, match="MOYSKLAD_SNACK_SALES_CHANNEL_ID"):
        validate_daily_sales_demand_worker_settings(Settings())


def test_enabled_prod_requires_snack_channel_not_coffee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snack = str(uuid4())
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DAILY_SALES_DEMAND_WORKER_ENABLED", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/test")
    monkeypatch.setenv("MOYSKLAD_API_TOKEN", "token")
    monkeypatch.setenv("MOYSKLAD_ORGANIZATION_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_PROJECT_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_DEMAND_AGENT_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_SNACK_SALES_CHANNEL_ID", snack)
    monkeypatch.delenv("MOYSKLAD_VENDING_COFFEE_SALES_CHANNEL_ID", raising=False)
    validate_daily_sales_demand_worker_settings(Settings())


def test_enabled_prod_accepts_valid_uuids(monkeypatch: pytest.MonkeyPatch) -> None:
    snack = str(uuid4())
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DAILY_SALES_DEMAND_WORKER_ENABLED", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/test")
    monkeypatch.setenv("MOYSKLAD_API_TOKEN", "token")
    monkeypatch.setenv("MOYSKLAD_ORGANIZATION_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_PROJECT_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_DEMAND_AGENT_ID", str(uuid4()))
    monkeypatch.setenv("MOYSKLAD_SNACK_SALES_CHANNEL_ID", snack)
    validate_daily_sales_demand_worker_settings(Settings())
