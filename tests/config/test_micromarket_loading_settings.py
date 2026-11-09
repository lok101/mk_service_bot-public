from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from src.config.micromarket_loading import MicromarketLoadingSettings
from src.config.mongodb import MongoSettings


def test_micromarket_stock_events_collection_default() -> None:
    assert MongoSettings().micromarket_stock_events_collection == "micromarket_stock_events"


def test_micromarket_warehouse_stock_snapshot_collection_default() -> None:
    assert (
        MongoSettings().micromarket_warehouse_stock_snapshot_collection
        == "micromarket_warehouse_stock_snapshot"
    )


def test_warehouse_stock_sync_defaults() -> None:
    settings = MicromarketLoadingSettings()
    assert settings.warehouse_stock_sync_interval_seconds == 180
    assert settings.warehouse_stock_staleness_alert_seconds == 360
    assert settings.warehouse_stock_sync_failure_backoff_seconds == 90
    assert settings.warehouse_stock_staleness_alert_cooldown_seconds == 900
    assert settings.warehouse_stock_cold_wait_seconds == 15


def test_warehouse_stock_staleness_rejects_below_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MICROMARKET_LOADING_WAREHOUSE_STOCK_SYNC_INTERVAL_SECONDS", "90")
    monkeypatch.setenv("MICROMARKET_LOADING_WAREHOUSE_STOCK_STALENESS_ALERT_SECONDS", "60")
    with pytest.raises(ValidationError):
        MicromarketLoadingSettings()


def test_micromarket_planograms_collection_default() -> None:
    assert MongoSettings().micromarket_planograms_collection == "micromarket_planograms"


def test_micromarket_sale_unresolved_alert_min_default_is_1() -> None:
    assert MicromarketLoadingSettings().sale_unresolved_alert_min == 1


def test_micromarket_sale_unresolved_alert_min_rejects_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MICROMARKET_SALE_UNRESOLVED_ALERT_MIN", "0")
    with pytest.raises(ValidationError):
        MicromarketLoadingSettings()


def test_micromarket_ms_product_folder_ids_default_empty() -> None:
    assert MicromarketLoadingSettings().ms_product_folder_ids == ()


def test_field_forms_public_base_url_default_empty() -> None:
    assert MicromarketLoadingSettings().field_forms_public_base_url == ""


def test_field_forms_public_base_url_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIELD_FORMS_PUBLIC_BASE_URL", "https://bot.example.com/")
    settings = MicromarketLoadingSettings()
    assert settings.field_forms_public_base_url == "https://bot.example.com"


def test_require_micromarket_inventory_now_ok_without_now_template() -> None:
    """happy: now gate needs base URL + now token secret; NOW template not required."""
    settings = MicromarketLoadingSettings.model_construct(
        field_forms_public_base_url="https://bot.example.com",
        inventory_form_now_token_secret=SecretStr("now-secret"),
        inventory_form_now_template_id=None,
        inventory_form_as_of_template_id="tpl-as-of",
    )
    assert settings.is_micromarket_inventory_now_configured is True
    settings.require_micromarket_inventory_now()


def test_require_micromarket_inventory_now_raises_when_base_url_empty() -> None:
    settings = MicromarketLoadingSettings.model_construct(
        field_forms_public_base_url="",
        inventory_form_now_token_secret=SecretStr("now-secret"),
    )
    assert settings.is_micromarket_inventory_now_configured is False
    with pytest.raises(ValueError, match="FIELD_FORMS_PUBLIC_BASE_URL"):
        settings.require_micromarket_inventory_now()


def test_require_micromarket_inventory_now_raises_when_now_secret_empty() -> None:
    settings = MicromarketLoadingSettings.model_construct(
        field_forms_public_base_url="https://bot.example.com",
        inventory_form_now_token_secret=None,
    )
    assert settings.is_micromarket_inventory_now_configured is False
    with pytest.raises(ValueError, match="MICROMARKET_INVENTORY_FORM_NOW_TOKEN_SECRET"):
        settings.require_micromarket_inventory_now()
