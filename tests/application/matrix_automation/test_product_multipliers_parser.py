from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.matrix_automation.errors import ProductMultipliersParseError
from src.application.matrix_automation.sheets.product_multipliers import (
    parse_product_multipliers_sheet,
)

_MIN = Decimal("0.8")
_MAX = Decimal("3.0")
_HEADER = ["product_code", "product_name", "multiplier"]


def test_missing_header_row_raises_structural_error() -> None:
    with pytest.raises(ProductMultipliersParseError, match="missing product_multipliers header"):
        parse_product_multipliers_sheet([], min_bound=_MIN, max_bound=_MAX)


def test_header_only_returns_empty_multipliers_map() -> None:
    result = parse_product_multipliers_sheet([_HEADER], min_bound=_MIN, max_bound=_MAX)
    assert result.multipliers == {}
    assert result.product_block_map == {}


def test_duplicate_product_code_adds_product_block() -> None:
    rows = [
        _HEADER,
        ["A", "One", "1.0"],
        ["A", "Two", "1.2"],
    ]
    result = parse_product_multipliers_sheet(rows, min_bound=_MIN, max_bound=_MAX)
    assert "A" not in result.multipliers
    assert result.product_block_map["A"].detail == "duplicate_product_multiplier: A"


def test_out_of_bounds_multiplier_adds_product_block() -> None:
    rows = [_HEADER, ["A", "One", "5.0"]]
    result = parse_product_multipliers_sheet(rows, min_bound=_MIN, max_bound=_MAX)
    assert "A" not in result.multipliers
    assert result.product_block_map["A"].detail == "product_multiplier_out_of_bounds: A"


def test_invalid_row_adds_product_block() -> None:
    rows = [_HEADER, ["", "Ghost", "1.0"]]
    result = parse_product_multipliers_sheet(rows, min_bound=_MIN, max_bound=_MAX)
    assert result.multipliers == {}
    assert any("invalid_product_row" in block.detail for block in result.product_block_map.values())


def test_parse_product_multipliers_uses_comma_decimal_via_sheet_format() -> None:
    rows = [
        ["product_code", "name", "multiplier"],
        ["SKU1", "Name", "1,25"],
    ]
    result = parse_product_multipliers_sheet(
        rows,
        min_bound=Decimal("0.8"),
        max_bound=Decimal("3.0"),
    )
    assert result.multipliers["SKU1"] == Decimal("1.25")
