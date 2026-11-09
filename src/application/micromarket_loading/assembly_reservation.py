from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.warehouse_stock_snapshot import MainWarehouseStockSnapshot
from src.domain.micromarket_loading.assembly_order import (
    MicromarketAssemblyOrder,
    reserved_qty_by_catalog_code,
)


@beartype
def available_qty_by_catalog_code(
    *,
    snapshot: MainWarehouseStockSnapshot | None,
    open_orders: tuple[MicromarketAssemblyOrder, ...],
) -> Mapping[str, Decimal]:
    """available = snapshot − Σ open assembly reservations (global warehouse)."""
    reserved = reserved_qty_by_catalog_code(open_orders)
    if snapshot is None:
        return {code: Decimal("0") for code in reserved}
    available: dict[str, Decimal] = {}
    codes = set(snapshot.qty_by_catalog_code) | set(reserved)
    for code in codes:
        stock = snapshot.qty_by_catalog_code.get(code, Decimal("0"))
        hold = reserved.get(code, Decimal("0"))
        value = stock - hold
        available[code] = value if value > 0 else Decimal("0")
    return available


@beartype
def available_for_code(
    *,
    snapshot: MainWarehouseStockSnapshot | None,
    open_orders: tuple[MicromarketAssemblyOrder, ...],
    catalog_code: str,
) -> Decimal:
    return available_qty_by_catalog_code(
        snapshot=snapshot,
        open_orders=open_orders,
    ).get(catalog_code.strip(), Decimal("0"))
