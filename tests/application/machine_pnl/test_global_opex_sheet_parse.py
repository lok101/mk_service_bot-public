from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.application.machine_pnl.errors import GlobalOpExSheetError
from src.application.machine_pnl.global_opex_sheet import parse_global_opex_sheet_rows


def test_global_opex_sheet_rejects_bad_header() -> None:
    # error
    with pytest.raises(GlobalOpExSheetError):
        parse_global_opex_sheet_rows([["from", "labor", "acq", "fee", "term"]])


def test_global_opex_sheet_parses_ru_cells() -> None:
    # happy
    rows = [
        [
            "valid_from",
            "labor_rate_global",
            "acquiring_percent",
            "acquiring_fee_per_sale",
            "terminal_monthly",
        ],
        ["05.08.2026", "150,00", "2,52%", "0,20", "990"],
    ]
    parsed = parse_global_opex_sheet_rows(rows)
    assert len(parsed) == 1
    assert parsed[0].valid_from == date(2026, 8, 5)
    assert parsed[0].labor_rate_global == Decimal("150.00")
    assert parsed[0].acquiring_percent == Decimal("2.52")
    assert parsed[0].acquiring_fee_per_sale == Decimal("0.20")
    assert parsed[0].terminal_monthly == Decimal("990")


def test_global_opex_sheet_skips_empty_row_and_rejects_bad_cell() -> None:
    # edge + error
    header = [
        "valid_from",
        "labor_rate_global",
        "acquiring_percent",
        "acquiring_fee_per_sale",
        "terminal_monthly",
    ]
    ok = parse_global_opex_sheet_rows(
        [header, ["", "", "", "", ""], ["2026-01-01", "10", "1", "0", "100"]]
    )
    assert len(ok) == 1
    with pytest.raises(GlobalOpExSheetError):
        parse_global_opex_sheet_rows([header, ["05.08.2026", "not-a-number", "1", "0", "100"]])


def test_global_opex_sheet_empty_optional_rates_are_none() -> None:
    header = [
        "valid_from",
        "labor_rate_global",
        "acquiring_percent",
        "acquiring_fee_per_sale",
        "terminal_monthly",
    ]
    parsed = parse_global_opex_sheet_rows([header, ["05.08.2026", "", "", "", ""]])
    assert len(parsed) == 1
    assert parsed[0].labor_rate_global is None
    assert parsed[0].acquiring_percent is None
    assert parsed[0].acquiring_fee_per_sale is None
    assert parsed[0].terminal_monthly is None
