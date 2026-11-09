from __future__ import annotations

import pytest

from src.config.machine_pnl import MachinePnlSettings
from src.config.machine_pnl_month import MachinePnlMonthSettings
from src.config.settings import Settings
from src.infrastructure.composition.wiring.assemble_machine_pnl_month_worker import (
    assemble_machine_pnl_month_worker,
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


def test_assemble_disabled_worker_does_not_require_sheets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(machine_pnl_month=MachinePnlMonthSettings(worker_enabled=False))
    container = assemble_machine_pnl_month_worker(settings)
    assert container is not None


def test_assemble_enabled_worker_requires_sheet_ids(monkeypatch: pytest.MonkeyPatch) -> None:
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
        assemble_machine_pnl_month_worker(settings)
