from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.config.technician_warehouse import TechnicianWarehouseSettings


def test_defaults_keep_supply_codes_optional_and_lookback_sixty() -> None:
    settings = TechnicianWarehouseSettings()
    assert settings.supply_store_codes == ()
    assert settings.ms_lookback_days == 60


def test_supply_codes_are_trimmed_deduplicated_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES", " main,returns, main ")
    assert TechnicianWarehouseSettings().supply_store_codes == ("main", "returns")


@pytest.mark.parametrize("value", ["-1", "91"])
def test_lookback_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_MS_LOOKBACK_DAYS", value)
    with pytest.raises(ValidationError):
        TechnicianWarehouseSettings()


@pytest.mark.parametrize("value", ["0", "90"])
def test_lookback_accepts_bounds(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TECHNICIAN_WAREHOUSE_MS_LOOKBACK_DAYS", value)
    assert TechnicianWarehouseSettings().ms_lookback_days == int(value)


def test_technician_warehouse_collection_default() -> None:
    assert MongoSettings().technician_warehouse_events_collection == "technician_warehouse_events"


def test_settings_keeps_technician_warehouse_supply_codes_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert settings.technician_warehouse.supply_store_codes == ()
    assert settings.technician_warehouse.ms_lookback_days == 60
