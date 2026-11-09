from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings
from src.config.service_visits import ServiceVisitsSettings
from src.config.settings import Settings, validate_service_visits_worker_settings


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
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("SERVICE_VISITS_WORKER_ENABLED", raising=False)


def test_service_visits_worker_defaults_disabled() -> None:
    settings = ServiceVisitsSettings()
    assert settings.worker_enabled is False
    assert settings.visits_collection == "service_visits"
    assert settings.worker_status_collection == "service_visits_worker_status"


def test_no_sales_min_baseline_qty_defaults_to_zero() -> None:
    settings = ServiceVisitsSettings()
    assert settings.no_sales_min_baseline_qty == Decimal("0")


def test_no_sales_min_baseline_qty_rejects_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_VISITS_NO_SALES_MIN_BASELINE_QTY", "-1")
    with pytest.raises(ValidationError):
        ServiceVisitsSettings()


def test_task_notify_defaults_disabled() -> None:
    """happy: notify off; chat id None."""
    settings = ServiceVisitsSettings()
    assert settings.task_notify_enabled is False
    assert settings.task_notify_telegram_chat_id is None


def test_task_notify_enabled_requires_chat_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: ENABLED=true без chat id → ValidationError."""
    monkeypatch.setenv("SERVICE_VISITS_TASK_NOTIFY_ENABLED", "true")
    monkeypatch.delenv("SERVICE_VISITS_TASK_NOTIFY_TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValidationError):
        ServiceVisitsSettings()


def test_task_notify_enabled_with_chat_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy: enabled + chat id ok."""
    monkeypatch.setenv("SERVICE_VISITS_TASK_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("SERVICE_VISITS_TASK_NOTIFY_TELEGRAM_CHAT_ID", "-100123")
    settings = ServiceVisitsSettings()
    assert settings.task_notify_enabled is True
    assert settings.task_notify_telegram_chat_id == -100123


def test_validate_disabled_skips_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    validate_service_visits_worker_settings(settings)


def test_validate_enabled_without_mongo_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(
        service_visits=ServiceVisitsSettings.model_construct(worker_enabled=True),
        mongodb=MongoSettings.model_construct(uri=None),
    )
    with pytest.raises(ValueError, match="MONGODB_URI must be set"):
        validate_service_visits_worker_settings(settings)
