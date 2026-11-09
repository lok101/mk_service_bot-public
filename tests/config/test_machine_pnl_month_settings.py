from __future__ import annotations

import pytest

from src.config.google_sheets import GoogleSheetsSettings
from src.config.machine_pnl import MachinePnlSettings
from src.config.machine_pnl_month import MachinePnlMonthSettings
from src.config.mongodb import MongoSettings
from src.config.settings import (
    Settings,
    validate_machine_pnl_month_settings,
    validate_machine_pnl_month_worker_settings,
)


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


def test_month_defaults_disabled() -> None:
    s = MachinePnlMonthSettings()
    assert s.enabled is False
    assert s.ratio_lookback_periods == 3
    assert s.worker_enabled is False
    assert s.worker_interval_hours == 24
    assert s.sheet_spreadsheet_id is None
    assert s.sheet_id is None
    assert s.snapshot_collection == "machine_pnl_month_snapshot"


def test_mongodb_month_worker_status_collection_default() -> None:
    m = MongoSettings()
    assert m.machine_pnl_month_worker_status_collection == "machine_pnl_month_worker_status"


def test_disabled_skips_sheet_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    validate_machine_pnl_month_settings(Settings())
    validate_machine_pnl_month_worker_settings(Settings())


def test_month_enabled_requires_period_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(
        machine_pnl=MachinePnlSettings(enabled=False),
        machine_pnl_month=MachinePnlMonthSettings(enabled=True),
    )
    with pytest.raises(ValueError, match="MACHINE_PNL_ENABLED"):
        validate_machine_pnl_month_settings(settings)


def test_worker_enabled_requires_sheet_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(
        machine_pnl=MachinePnlSettings(
            enabled=True,
            unit_cost_spreadsheet_id="ss",
            unit_cost_sheet_id=1,
            global_opex_spreadsheet_id="ss",
            global_opex_sheet_id=2,
            location_rent_spreadsheet_id="ss",
            location_rent_sheet_id=3,
        ),
        machine_pnl_month=MachinePnlMonthSettings(enabled=True, worker_enabled=True),
    )
    with pytest.raises(ValueError, match="MACHINE_PNL_MONTH_SHEET"):
        validate_machine_pnl_month_worker_settings(settings)


def _month_worker_on(**google_overrides: object) -> Settings:
    sheets_fields: dict[str, object] = {
        "technicians_directory_spreadsheet_id": "",
        "technicians_directory_sheet_id": None,
        "locations_directory_spreadsheet_id": "",
        "locations_directory_sheet_id": None,
    }
    sheets_fields.update(google_overrides)
    return Settings(
        machine_pnl=MachinePnlSettings(
            enabled=True,
            unit_cost_spreadsheet_id="ss",
            unit_cost_sheet_id=1,
            global_opex_spreadsheet_id="ss",
            global_opex_sheet_id=2,
            location_rent_spreadsheet_id="ss",
            location_rent_sheet_id=3,
        ),
        machine_pnl_month=MachinePnlMonthSettings(
            enabled=True,
            worker_enabled=True,
            sheet_spreadsheet_id="month-ss",
            sheet_id=9,
        ),
        mongodb=MongoSettings.model_construct(uri="mongodb://localhost:27017/test"),
        google_sheets=GoogleSheetsSettings.model_construct(**sheets_fields),
    )


def test_worker_enabled_requires_locations_directory_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    settings = _month_worker_on(
        technicians_directory_spreadsheet_id="tech-ss",
        technicians_directory_sheet_id=7,
    )
    with pytest.raises(ValueError, match="LOCATIONS_DIRECTORY"):
        validate_machine_pnl_month_worker_settings(settings)


def test_worker_enabled_requires_technicians_directory_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    settings = _month_worker_on(
        locations_directory_spreadsheet_id="loc-ss",
        locations_directory_sheet_id=11,
    )
    with pytest.raises(ValueError, match="TECHNICIANS_DIRECTORY"):
        validate_machine_pnl_month_worker_settings(settings)


def test_worker_enabled_ok_with_both_directory_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    settings = _month_worker_on(
        technicians_directory_spreadsheet_id="tech-ss",
        technicians_directory_sheet_id=7,
        locations_directory_spreadsheet_id="loc-ss",
        locations_directory_sheet_id=11,
    )
    validate_machine_pnl_month_worker_settings(settings)
