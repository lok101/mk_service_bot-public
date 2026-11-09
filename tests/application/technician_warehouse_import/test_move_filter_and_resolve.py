from __future__ import annotations

from decimal import Decimal

from .fakes import (
    _run_import,
    _supply_in,
    _supply_return,
    _technician_to_machine,
)


def test_import_accepts_supply_in_and_return_only() -> None:
    result, warehouse = _run_import(_supply_in("in-1"), _supply_return("ret-1"))
    assert result.imported == 2
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("7")


def test_import_ignores_technician_to_machine_move() -> None:
    result, warehouse = _run_import(_technician_to_machine("visibility-1"))
    assert result.ignored == 1
    assert warehouse.calculated_stock_since_baseline() == {}


def test_import_resolves_primary_and_alias_product_codes() -> None:
    result, warehouse = _run_import(
        _supply_in("primary", product_code="coffee-id"),
        _supply_in("alias", product_code="coffee-rich-alias"),
    )
    assert result.unmatched_products == ()
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("20")
