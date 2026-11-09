from __future__ import annotations

from decimal import Decimal

from tests.domain.technician_warehouse.helpers import (
    _T1,
    _T2,
    _TECHNICIAN_ID,
    _supply_event,
    _warehouse_with_baseline,
)

from src.domain.technician_warehouse import TechnicianWarehouse, TransferDirection


def test_book_stock_none_without_inventory() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    assert warehouse.book_stock_since_latest_inventory() is None


def test_book_stock_uses_latest_inventory_and_later_transfers() -> None:
    warehouse = _warehouse_with_baseline({"coffee": Decimal("40")})
    warehouse.observe_transfer(
        _supply_event("in-1", "20", TransferDirection.SUPPLY_IN, updated_at=_T2),
    )
    book = warehouse.book_stock_since_latest_inventory()
    assert book is not None
    assert book.as_of == _T1
    assert book.stock_by_sku == {"coffee": Decimal("60")}
