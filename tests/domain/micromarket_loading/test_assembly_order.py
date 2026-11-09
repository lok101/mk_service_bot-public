from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    DuplicateCatalogCode,
    InvalidAssemblyOrderTransition,
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
    find_duplicate_on_machine,
    reserved_qty_by_catalog_code,
)

_MACHINE = "701"
_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def _line(code: str, qty: str = "2") -> MicromarketAssemblyOrderLine:
    return MicromarketAssemblyOrderLine(catalog_code=code, qty=Decimal(qty))


def _order(
    order_id: str = "ao-1",
    *,
    lines: tuple[MicromarketAssemblyOrderLine, ...] | None = None,
    status: AssemblyOrderStatus = AssemblyOrderStatus.OPEN,
) -> MicromarketAssemblyOrder:
    return MicromarketAssemblyOrder(
        order_id=order_id,
        machine_code=_MACHINE,
        lines=lines or (_line("SKU-A"),),
        status=status,
        created_at=_NOW,
    )


def test_open_order_holds_lines() -> None:
    order = _order(lines=(_line("SKU-A", "3"), _line("SKU-B", "1")))
    assert order.status is AssemblyOrderStatus.OPEN
    assert order.lines[0].qty == Decimal("3")


def test_cancel_and_consume_happy() -> None:
    cancelled = _order().cancel()
    assert isinstance(cancelled, MicromarketAssemblyOrder)
    assert cancelled.status is AssemblyOrderStatus.CANCELLED
    consumed = _order(order_id="ao-2").consume()
    assert isinstance(consumed, MicromarketAssemblyOrder)
    assert consumed.status is AssemblyOrderStatus.CONSUMED


def test_cancel_when_not_open_is_error() -> None:
    order = _order(status=AssemblyOrderStatus.CANCELLED)
    result = order.cancel()
    assert isinstance(result, InvalidAssemblyOrderTransition)


def test_duplicate_code_inside_order_raises() -> None:
    with pytest.raises(ValueError, match="duplicate catalog_code"):
        _order(lines=(_line("SKU-A"), _line("SKU-A")))


def test_find_duplicate_on_machine_across_open_orders() -> None:
    existing = _order(lines=(_line("SKU-A"),))
    dup = find_duplicate_on_machine(
        machine_code=_MACHINE,
        candidate_codes=("SKU-A",),
        open_orders=(existing,),
    )
    assert isinstance(dup, DuplicateCatalogCode)
    assert dup.catalog_code == "SKU-A"


def test_find_duplicate_ignores_other_machine_and_exclude() -> None:
    other = MicromarketAssemblyOrder(
        order_id="ao-x",
        machine_code="702",
        lines=(_line("SKU-A"),),
        created_at=_NOW,
    )
    same = _order(order_id="ao-edit", lines=(_line("SKU-A"),))
    assert (
        find_duplicate_on_machine(
            machine_code=_MACHINE,
            candidate_codes=("SKU-A",),
            open_orders=(other, same),
            exclude_order_id="ao-edit",
        )
        is None
    )


def test_reserved_qty_sums_open_only() -> None:
    open_a = _order(order_id="1", lines=(_line("SKU-A", "2"),))
    open_b = _order(order_id="2", lines=(_line("SKU-A", "3"), _line("SKU-B", "1")))
    cancelled = _order(
        order_id="3",
        lines=(_line("SKU-A", "9"),),
        status=AssemblyOrderStatus.CANCELLED,
    )
    totals = reserved_qty_by_catalog_code((open_a, open_b, cancelled))
    assert totals["SKU-A"] == Decimal("5")
    assert totals["SKU-B"] == Decimal("1")


def test_alerted_day_record() -> None:
    order = _order()
    day = date(2026, 10, 28)
    assert order.was_alerted(operational_day=day) is False
    order.record_alert(operational_day=day)
    assert order.was_alerted(operational_day=day) is True
