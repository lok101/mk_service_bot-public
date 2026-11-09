from __future__ import annotations

from decimal import Decimal

from src.domain.micromarket_loading.quantities import initial_launch_qty, need_qty


def test_need_qty_clamps_at_zero() -> None:
    assert need_qty(target_qty=2, shelf_qty=Decimal("5")) == Decimal("0")


def test_need_qty_keeps_full_target_when_shelf_empty() -> None:
    assert need_qty(target_qty=4, shelf_qty=Decimal("0")) == Decimal("4")


def test_initial_launch_qty_is_min_of_need_and_warehouse() -> None:
    assert initial_launch_qty(need_qty=Decimal("9"), warehouse_qty=Decimal("3")) == Decimal("3")
    assert initial_launch_qty(need_qty=Decimal("2"), warehouse_qty=Decimal("8")) == Decimal("2")
    assert initial_launch_qty(need_qty=Decimal("2"), warehouse_qty=Decimal("-1")) == Decimal("0")
