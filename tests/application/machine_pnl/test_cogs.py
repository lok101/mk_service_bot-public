from __future__ import annotations

from decimal import Decimal

from src.application.machine_pnl.cogs import (
    cogs_actual_for_line,
    cogs_expected_for_line,
    physical_qty,
)


def test_physical_qty_from_stock_identity() -> None:
    assert physical_qty(
        actual_prev=Decimal("10"),
        loads_total=Decimal("2"),
        actual=Decimal("7"),
    ) == Decimal("5")


def test_cogs_expected_sales_times_cost() -> None:
    assert cogs_expected_for_line(
        sales_total=Decimal("3"),
        unit_cost=Decimal("10.5"),
    ) == Decimal("31.5")


def test_cogs_actual_negative_physical_qty() -> None:
    qty = physical_qty(
        actual_prev=Decimal("1"),
        loads_total=Decimal("0"),
        actual=Decimal("5"),
    )
    assert qty == Decimal("-4")
    assert cogs_actual_for_line(physical=qty, unit_cost=Decimal("2")) == Decimal("-8")
