from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.snack_loading.matrix_stock_provider import DomainMatrixStockProvider
from src.domain.snack_loading import SnackMachineStock
from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore


def test_matrix_stock_provider_returns_cell_qty() -> None:
    store = InMemorySnackMachineStockStore()
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 3): Decimal("4")},
        product_by_key={("514", "SnackA", 3): "SKU1"},
        inventory_id="i1",
    )
    store.save(stock)
    provider = DomainMatrixStockProvider(store)
    assert (
        provider.current_stock(
            machine_code="514",
            logical_matrix_name="SnackA",
            line_number=3,
            product_code="SKU1",
        )
        == 4
    )


def test_matrix_stock_provider_unknown_machine_returns_none() -> None:
    provider = DomainMatrixStockProvider(InMemorySnackMachineStockStore())
    assert (
        provider.current_stock(
            machine_code="x",
            logical_matrix_name="M",
            line_number=1,
            product_code="P",
        )
        is None
    )


def test_matrix_stock_provider_product_mismatch_returns_none() -> None:
    store = InMemorySnackMachineStockStore()
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 3): Decimal("4")},
        product_by_key={("514", "SnackA", 3): "SKU1"},
        inventory_id="i1",
    )
    store.save(stock)
    provider = DomainMatrixStockProvider(store)
    assert (
        provider.current_stock(
            machine_code="514",
            logical_matrix_name="SnackA",
            line_number=3,
            product_code="OTHER",
        )
        is None
    )


def test_matrix_stock_provider_non_integral_qty_returns_none() -> None:
    store = InMemorySnackMachineStockStore()
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 3): Decimal("1.5")},
        product_by_key={("514", "SnackA", 3): "SKU1"},
        inventory_id="i1",
    )
    store.save(stock)
    provider = DomainMatrixStockProvider(store)
    assert (
        provider.current_stock(
            machine_code="514",
            logical_matrix_name="SnackA",
            line_number=3,
            product_code="SKU1",
        )
        is None
    )
