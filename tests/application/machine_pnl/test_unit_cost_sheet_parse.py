from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.application.machine_pnl.errors import UnitCostSheetError
from src.application.machine_pnl.unit_cost import UnitCostRow
from src.application.machine_pnl.unit_cost_sheet import parse_unit_cost_sheet_rows

_CANONICAL_HEADER = ["product_code", "unit_cost", "valid_from", "valid_to"]


def test_unit_cost_catalog_rejects_bad_header() -> None:
    with pytest.raises(UnitCostSheetError):
        parse_unit_cost_sheet_rows([["sku", "cost", "from", "to"]])


def test_parse_unit_cost_sheet_rows_happy_canonical_header() -> None:
    rows = parse_unit_cost_sheet_rows(
        [
            _CANONICAL_HEADER,
            ["SKU-1", "12.50", "2026-01-01", "2026-06-30"],
            ["SKU-2", "3", "2026-02-01", ""],
        ]
    )
    assert rows == (
        UnitCostRow(
            product_code="SKU-1",
            unit_cost=Decimal("12.50"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 6, 30),
        ),
        UnitCostRow(
            product_code="SKU-2",
            unit_cost=Decimal("3"),
            valid_from=date(2026, 2, 1),
            valid_to=None,
        ),
    )


def test_parse_unit_cost_sheet_rows_rejects_duplicate_product_valid_from() -> None:
    with pytest.raises(UnitCostSheetError):
        parse_unit_cost_sheet_rows(
            [
                _CANONICAL_HEADER,
                ["SKU-1", "1.00", "2026-01-01", ""],
                ["SKU-1", "2.00", "2026-01-01", "2026-12-31"],
            ]
        )


def test_parse_unit_cost_sheet_rows_skips_empty_row() -> None:
    rows = parse_unit_cost_sheet_rows(
        [
            _CANONICAL_HEADER,
            ["", "", "", ""],
            ["SKU-1", "1.00", "2026-01-01", ""],
        ]
    )
    assert rows == (
        UnitCostRow(
            product_code="SKU-1",
            unit_cost=Decimal("1.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
        ),
    )


def test_parse_unit_cost_sheet_rows_accepts_ru_decimal_and_date() -> None:
    rows = parse_unit_cost_sheet_rows(
        [
            _CANONICAL_HEADER,
            ["16161616003327", "1,26", "01.06.2026", ""],
            ["16161616003317", "0,66", "01.06.2026", "15.06.2026"],
        ]
    )
    assert rows == (
        UnitCostRow(
            product_code="16161616003327",
            unit_cost=Decimal("1.26"),
            valid_from=date(2026, 6, 1),
            valid_to=None,
        ),
        UnitCostRow(
            product_code="16161616003317",
            unit_cost=Decimal("0.66"),
            valid_from=date(2026, 6, 1),
            valid_to=date(2026, 6, 15),
        ),
    )


def test_parse_unit_cost_sheet_rows_rejects_invalid_ru_unit_cost() -> None:
    with pytest.raises(UnitCostSheetError, match="invalid unit_cost"):
        parse_unit_cost_sheet_rows(
            [
                _CANONICAL_HEADER,
                ["SKU-1", "#REF!", "01.06.2026", ""],
            ]
        )


def test_parse_unit_cost_sheet_rows_rejects_invalid_ru_valid_from() -> None:
    with pytest.raises(UnitCostSheetError, match="invalid valid_from"):
        parse_unit_cost_sheet_rows(
            [
                _CANONICAL_HEADER,
                ["SKU-1", "1,26", "not-a-date", ""],
            ]
        )
