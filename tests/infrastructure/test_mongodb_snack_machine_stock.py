from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock
import pytest

from src.domain.snack_loading import SnackMachineStock
from src.domain.snack_loading.errors import SnackStockConcurrencyError
from src.infrastructure.mongodb.snack_machine_stock import MongoSnackMachineStockStore


def test_mongo_snack_machine_stock_save_conflict_raises() -> None:
    # error: два агрегата с одной loaded_version
    collection = mongomock.MongoClient().db.snack_machine_stock_events
    store = MongoSnackMachineStockStore.from_collection(collection)
    base = SnackMachineStock(machine_code="514")
    base.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="inv-1",
    )
    store.save(base)
    a = store.load("514")
    b = store.load("514")
    assert a is not None and b is not None
    a.apply_sale_deduct(
        source_id="s-a",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    b.apply_sale_deduct(
        source_id="s-b",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    store.save(a)
    with pytest.raises(SnackStockConcurrencyError):
        store.save(b)
    loaded = store.load("514")
    assert loaded is not None
    assert loaded.qty("514", "SnackA", 1) == Decimal("4")


def test_mongo_snack_machine_stock_save_load_roundtrip() -> None:
    collection = mongomock.MongoClient().db.snack_machine_stock_events
    store = MongoSnackMachineStockStore.from_collection(collection)

    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="inv-1",
    )
    stock.apply_sale_deduct(
        source_id="s1",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("2"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    store.save(stock)

    loaded = store.load("514")
    assert loaded is not None
    assert loaded.qty("514", "SnackA", 1) == Decimal("3")
    assert loaded.product("514", "SnackA", 1) == "SKU1"
    assert loaded.has_completed_inventory is True
