from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.application.machine_pnl.composed_opex_params import ComposedOpExParamsCatalog
from src.domain.ids import MachineId
from src.infrastructure.machine_pnl.sheets_global_opex_catalog import (
    build_composed_opex_from_rows,
    load_global_opex_sheet_rows,
)


def test_load_global_opex_sheet_rows_wraps_read_sheet_rows(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_read(**kwargs: object) -> list[list[str]]:
        captured.update(kwargs)
        return [
            [
                "valid_from",
                "labor_rate_global",
                "acquiring_percent",
                "acquiring_fee_per_sale",
                "terminal_monthly",
            ]
        ]

    monkeypatch.setattr(
        "src.infrastructure.machine_pnl.sheets_global_opex_catalog.read_sheet_rows",
        fake_read,
    )
    rows = load_global_opex_sheet_rows(
        credentials_file="creds.json",
        spreadsheet_id="ss",
        sheet_id=10,
    )
    assert captured["spreadsheet_id"] == "ss"
    assert captured["sheet_id"] == 10
    assert rows[0][0] == "valid_from"


def test_build_composed_opex_from_sheet_rows() -> None:
    # happy: parse → ComposedOpExParamsCatalog with FixtureOpExParamsCatalog.default() machine
    rows = [
        [
            "valid_from",
            "labor_rate_global",
            "acquiring_percent",
            "acquiring_fee_per_sale",
            "terminal_monthly",
        ],
        ["2026-01-01", "50", "2,5", "0,2", "900"],
    ]
    catalog = build_composed_opex_from_rows(rows)
    assert isinstance(catalog, ComposedOpExParamsCatalog)
    params = catalog.resolve(MachineId("101"), as_of=date(2026, 7, 1))
    assert params.labor_rate == Decimal("50")
    assert params.missing_labor_rate is False
