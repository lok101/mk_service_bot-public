from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.settings import Settings


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
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_execute_disabled_allows_empty_move_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MICROMARKET_LOADING_EXECUTE_ENABLED", "false")
    monkeypatch.delenv("TELEGRAM_ALERT_CHAT_ID", raising=False)
    settings = Settings()
    assert settings.micromarket_loading.execute_enabled is False


def test_legacy_assembly_orders_day_alert_env_absent_or_present_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removed day-alert flag: Settings loads with env absent or leftover."""
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MICROMARKET_LOADING_EXECUTE_ENABLED", "false")
    monkeypatch.delenv("MICROMARKET_ASSEMBLY_ORDERS_DAY_ALERT_ENABLED", raising=False)
    settings = Settings()
    assert not hasattr(settings.micromarket_loading, "assembly_orders_day_alert_enabled")
    monkeypatch.setenv("MICROMARKET_ASSEMBLY_ORDERS_DAY_ALERT_ENABLED", "true")
    leftover = Settings()
    assert not hasattr(leftover.micromarket_loading, "assembly_orders_day_alert_enabled")


def test_execute_enabled_requires_warehouse_org_project_paths_and_alert_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MICROMARKET_LOADING_EXECUTE_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_ALERT_CHAT_ID", raising=False)
    with pytest.raises(ValidationError) as caught:
        Settings()
    text = str(caught.value)
    assert "MICROMARKET_LOADING_MAIN_WAREHOUSE_ID" in text
    assert "MICROMARKET_LOADING_ORGANIZATION_ID" in text
    assert "MICROMARKET_LOADING_PROJECT_ID" in text
    assert "MICROMARKET_LOADING_PRODUCTS_PATH" in text
    assert "MICROMARKET_LOADING_WAREHOUSES_PATH" in text
    assert "TELEGRAM_ALERT_CHAT_ID" in text


def test_execute_enabled_accepts_complete_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MICROMARKET_LOADING_EXECUTE_ENABLED", "true")
    monkeypatch.setenv(
        "MICROMARKET_LOADING_MAIN_WAREHOUSE_ID",
        "11111111-1111-1111-1111-111111111111",
    )
    monkeypatch.setenv(
        "MICROMARKET_LOADING_ORGANIZATION_ID",
        "22222222-2222-2222-2222-222222222222",
    )
    monkeypatch.setenv(
        "MICROMARKET_LOADING_PROJECT_ID",
        "33333333-3333-3333-3333-333333333333",
    )
    monkeypatch.setenv("MICROMARKET_LOADING_PRODUCTS_PATH", "Товары/Холодильник")
    monkeypatch.setenv("MICROMARKET_LOADING_WAREHOUSES_PATH", "Склады/Точки")
    monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", "-1001")
    settings = Settings()
    assert settings.micromarket_loading.execute_enabled is True
    assert settings.telegram.alert_chat_id == -1001


def test_order_events_collection_defaults() -> None:
    from src.config.mongodb import MongoSettings

    settings = MongoSettings()
    assert settings.micromarket_loading_order_events_collection == (
        "micromarket_loading_order_events"
    )
