from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.application.machine_pnl.unit_cost import UnitCostRow, effective_unit_cost


def test_effective_unit_cost_picks_max_valid_from() -> None:
    rows = (
        UnitCostRow("sku", Decimal("1"), date(2026, 1, 1), None),
        UnitCostRow("sku", Decimal("2"), date(2026, 6, 1), None),
        UnitCostRow("other", Decimal("9"), date(2026, 1, 1), None),
    )
    assert effective_unit_cost(rows, product_code="sku", as_of=date(2026, 7, 1)) == Decimal("2")


def test_effective_unit_cost_respects_valid_to_inclusive() -> None:
    rows = (UnitCostRow("sku", Decimal("5"), date(2026, 1, 1), date(2026, 3, 31)),)
    assert effective_unit_cost(rows, product_code="sku", as_of=date(2026, 3, 31)) == Decimal("5")
    assert effective_unit_cost(rows, product_code="sku", as_of=date(2026, 4, 1)) is None
