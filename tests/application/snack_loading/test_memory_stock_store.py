from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.snack_loading import SnackMachineStock
from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore


def test_memory_stock_store_save_load() -> None:
    store = InMemorySnackMachineStockStore()
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "M", 1): Decimal("2")},
        product_by_key={("514", "M", 1): "P"},
        inventory_id="i1",
    )
    store.save(stock)
    loaded = store.load("514")
    assert loaded is not None
    assert loaded.qty("514", "M", 1) == Decimal("2")
