from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.micromarket_loading.assembly_reservation import (
    available_for_code,
    available_qty_by_catalog_code,
)
from src.application.micromarket_loading.warehouse_stock_snapshot import MainWarehouseStockSnapshot
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
)

_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_WH = UUID("00000000-0000-4000-8000-000000000001")


def _order(code: str, qty: str, *, order_id: str = "ao-1") -> MicromarketAssemblyOrder:
    return MicromarketAssemblyOrder(
        order_id=order_id,
        machine_code="701",
        lines=(MicromarketAssemblyOrderLine(catalog_code=code, qty=Decimal(qty)),),
        created_at=_NOW,
    )


def test_available_subtracts_open_reservations() -> None:
    snapshot = MainWarehouseStockSnapshot(
        warehouse_id=_WH,
        refreshed_at=_NOW,
        qty_by_catalog_code={"SKU-A": Decimal("10"), "SKU-B": Decimal("4")},
    )
    open_orders = (_order("SKU-A", "3"), _order("SKU-A", "2", order_id="ao-2"))
    available = available_qty_by_catalog_code(snapshot=snapshot, open_orders=open_orders)
    assert available["SKU-A"] == Decimal("5")
    assert available["SKU-B"] == Decimal("4")


def test_available_clamps_at_zero() -> None:
    snapshot = MainWarehouseStockSnapshot(
        warehouse_id=_WH,
        refreshed_at=_NOW,
        qty_by_catalog_code={"SKU-A": Decimal("1")},
    )
    assert available_for_code(
        snapshot=snapshot,
        open_orders=(_order("SKU-A", "5"),),
        catalog_code="SKU-A",
    ) == Decimal("0")


def test_available_without_snapshot_is_zero() -> None:
    assert available_for_code(
        snapshot=None,
        open_orders=(_order("SKU-A", "1"),),
        catalog_code="SKU-A",
    ) == Decimal("0")


def test_cancelled_not_in_reservation() -> None:
    snapshot = MainWarehouseStockSnapshot(
        warehouse_id=_WH,
        refreshed_at=_NOW,
        qty_by_catalog_code={"SKU-A": Decimal("10")},
    )
    cancelled = MicromarketAssemblyOrder(
        order_id="ao-c",
        machine_code="701",
        lines=(MicromarketAssemblyOrderLine(catalog_code="SKU-A", qty=Decimal("9")),),
        status=AssemblyOrderStatus.CANCELLED,
        created_at=_NOW,
    )
    assert available_for_code(
        snapshot=snapshot,
        open_orders=(cancelled,),
        catalog_code="SKU-A",
    ) == Decimal("10")
