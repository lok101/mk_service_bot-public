from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_WAREHOUSE = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_AT = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)


def test_replace_then_get_returns_snapshot() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    assert store.get() is None
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=_AT,
            qty_by_catalog_code={"SKU-1": Decimal("10")},
        ),
    )
    got = store.get()
    assert got is not None
    assert got.warehouse_id == _WAREHOUSE
    assert got.qty_by_catalog_code["SKU-1"] == Decimal("10")


def test_apply_delta_decrements_and_increments() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=_AT,
            qty_by_catalog_code={"SKU-1": Decimal("10"), "SKU-2": Decimal("3")},
        ),
    )
    store.apply_delta(deltas={"SKU-1": Decimal("-4")})
    assert store.get() is not None
    assert store.get().qty_by_catalog_code["SKU-1"] == Decimal("6")
    store.apply_delta(deltas={"SKU-1": Decimal("4")})
    assert store.get().qty_by_catalog_code["SKU-1"] == Decimal("10")


def test_apply_delta_clamps_below_zero() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=_AT,
            qty_by_catalog_code={"SKU-1": Decimal("2")},
        ),
    )
    store.apply_delta(deltas={"SKU-1": Decimal("-5")})
    assert store.get() is not None
    assert store.get().qty_by_catalog_code["SKU-1"] == Decimal("0")


def test_apply_delta_missing_code_starts_from_zero() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE,
            refreshed_at=_AT,
            qty_by_catalog_code={},
        ),
    )
    store.apply_delta(deltas={"NEW": Decimal("-1")})
    assert store.get() is not None
    assert store.get().qty_by_catalog_code["NEW"] == Decimal("0")


def test_apply_delta_without_snapshot_is_noop() -> None:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.apply_delta(deltas={"SKU-1": Decimal("-1")})
    assert store.get() is None
