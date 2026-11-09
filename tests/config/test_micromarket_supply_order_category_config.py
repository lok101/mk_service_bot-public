from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.config.micromarket_supply_order_category import MicromarketSupplyOrderCategorySettings

_DEFAULT_ATTR = UUID("c3b612d9-cc7d-11f1-0a80-1d46001735af")
_DEFAULT_SNACKS = UUID("4c2738f1-f43a-11ef-0a80-1a2b002150a4")
_DEFAULT_READY = UUID("7203a901-b1b2-11f1-0a80-115a00344501")


def test_defaults_threshold_and_prod_uuids() -> None:
    settings = MicromarketSupplyOrderCategorySettings()
    assert settings.shelf_life_days_threshold == 7
    assert settings.attr_shelf_life_days_id == _DEFAULT_ATTR
    assert settings.folder_snacks_id == _DEFAULT_SNACKS
    assert settings.folder_ready_meals_id == _DEFAULT_READY
    assert settings.sync_interval_seconds == 300
    assert settings.staleness_seconds == 600


def test_staleness_below_interval_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICROMARKET_SUPPLY_ORDER_CATEGORY_SYNC_INTERVAL_SECONDS", "300")
    monkeypatch.setenv("MICROMARKET_SUPPLY_ORDER_CATEGORY_STALENESS_SECONDS", "299")
    with pytest.raises(ValidationError):
        MicromarketSupplyOrderCategorySettings()


def test_custom_threshold_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICROMARKET_SUPPLY_SHELF_LIFE_DAYS_THRESHOLD", "14")
    settings = MicromarketSupplyOrderCategorySettings()
    assert settings.shelf_life_days_threshold == 14


@pytest.mark.parametrize(
    "env_name",
    (
        "MOYSKLAD_ATTR_SHELF_LIFE_DAYS_ID",
        "MOYSKLAD_FOLDER_SNACKS_ID",
        "MOYSKLAD_FOLDER_READY_MEALS_ID",
    ),
)
def test_empty_uuid_rejected(monkeypatch: pytest.MonkeyPatch, env_name: str) -> None:
    monkeypatch.setenv(env_name, "")
    with pytest.raises(ValidationError):
        MicromarketSupplyOrderCategorySettings()


@pytest.mark.parametrize(
    "env_name",
    (
        "MOYSKLAD_ATTR_SHELF_LIFE_DAYS_ID",
        "MOYSKLAD_FOLDER_SNACKS_ID",
        "MOYSKLAD_FOLDER_READY_MEALS_ID",
    ),
)
def test_invalid_uuid_rejected(monkeypatch: pytest.MonkeyPatch, env_name: str) -> None:
    monkeypatch.setenv(env_name, "not-a-uuid")
    with pytest.raises(ValidationError):
        MicromarketSupplyOrderCategorySettings()


def test_settings_nested_on_app_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.settings import Settings

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
    settings = Settings()
    assert settings.micromarket_supply_order_category.shelf_life_days_threshold == 7
    from src.config.settings import validate_micromarket_supply_order_category_settings

    validate_micromarket_supply_order_category_settings(settings)
