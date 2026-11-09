from __future__ import annotations

from decimal import Decimal

from beartype import beartype


@beartype
def need_qty(*, target_qty: int, shelf_qty: Decimal) -> Decimal:
    raw = Decimal(target_qty) - shelf_qty
    if raw < 0:
        return Decimal("0")
    return raw


@beartype
def initial_launch_qty(*, need_qty: Decimal, warehouse_qty: Decimal) -> Decimal:
    available = warehouse_qty if warehouse_qty > 0 else Decimal("0")
    if need_qty < available:
        return need_qty
    return available
