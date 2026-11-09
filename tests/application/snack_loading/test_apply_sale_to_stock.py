from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.snack_loading.apply_sale import ApplySnackSaleToStock
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.domain.snack_loading import SnackMachineStock, SnackStockConcurrencyError
from src.domain.snack_loading.events import SnackSaleDeducted, SnackStockAnomalyRecorded
from src.infrastructure.testing.snack_loading_fakes import (
    InMemoryKitMatrixDeployMapStore,
    InMemorySnackMachineStockStore,
)


def _sale(**kwargs: object) -> MachineSale:
    base: dict[str, object] = dict(
        source_id="s1",
        machine_id=MachineId("m1"),
        product_code="SKU1",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 2, tzinfo=UTC),
        sale_kind="snack",
        kit_matrix_id=42,
        kit_vending_machine_id=7,
        kit_line_number=1,
        machine_code="514",
        resolve_status=None,
    )
    base.update(kwargs)
    return MachineSale(**base)  # type: ignore[arg-type]


class _ConflictOnceStore(InMemorySnackMachineStockStore):
    def __init__(self) -> None:
        super().__init__()
        self._fails = 1

    def save(self, stock: SnackMachineStock) -> None:
        if self._fails > 0:
            self._fails -= 1
            raise SnackStockConcurrencyError(machine_code=stock.machine_code)
        super().save(stock)


class _MidBatchAnomalyConflictStore(InMemorySnackMachineStockStore):
    """First multi-event save persists only the first pending event, then conflicts."""

    def __init__(self) -> None:
        super().__init__()
        self._partial_done = False

    def save(self, stock: SnackMachineStock) -> None:
        if self._partial_done:
            super().save(stock)
            return
        stream = self._streams.setdefault(stock.machine_code, [])
        if len(stream) != stock.loaded_version:
            raise SnackStockConcurrencyError(machine_code=stock.machine_code)
        pending = stock.pull_events()
        if len(pending) < 2:
            stream.extend(pending)
            return
        stream.append(pending[0])
        self._partial_done = True
        raise SnackStockConcurrencyError(machine_code=stock.machine_code)


def test_apply_snack_sale_retries_on_stock_conflict() -> None:
    # error then happy
    stock_store = _ConflictOnceStore()
    stock_store._fails = 0
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)
    stock_store._fails = 1
    uc = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **_: "SKU1",
    )
    result = uc.execute(_sale())
    assert result.resolve_status == "resolved"
    assert stock_store.load("514").qty("514", "SnackA", 1) == Decimal("4")


def test_apply_snack_sale_oversell_mid_batch_retry_does_not_duplicate_anomaly() -> None:
    # error→happy: anomaly persisted, deduct not; retry must not duplicate anomaly
    stock_store = _MidBatchAnomalyConflictStore()
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("2")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)
    uc = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **_: "SKU1",
    )
    result = uc.execute(_sale(quantity=Decimal("5"), source_id="s-oversell"))
    assert result.resolve_status == "resolved"
    events = stock_store._streams.get("514", ())
    anomalies = [e for e in events if isinstance(e, SnackStockAnomalyRecorded)]
    deducts = [e for e in events if isinstance(e, SnackSaleDeducted)]
    assert len(anomalies) == 1
    assert anomalies[0].source_id == "s-oversell"
    assert len(deducts) == 1
    assert deducts[0].source_id == "s-oversell"
    assert stock_store.load("514").qty("514", "SnackA", 1) == Decimal("0")


def test_apply_sale_idempotent_by_source_id() -> None:
    stock_store = InMemorySnackMachineStockStore()
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)
    uc = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **_: "SKU1",
    )
    uc.execute(_sale())
    uc.execute(_sale())
    assert stock_store.load("514").qty("514", "SnackA", 1) == Decimal("4")


def test_apply_sale_product_mismatch_no_deduct() -> None:
    stock_store = InMemorySnackMachineStockStore()
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)
    uc = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **_: "OTHER",
    )
    result = uc.execute(_sale())
    assert result.resolve_status == "product_mismatch"
    assert stock_store.load("514").qty("514", "SnackA", 1) == Decimal("5")


def test_apply_sale_unresolved_matrix_no_deduct() -> None:
    stock_store = InMemorySnackMachineStockStore()
    uc = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=InMemoryKitMatrixDeployMapStore(),
        snapshot_product_lookup=lambda **_: None,
    )
    result = uc.execute(_sale())
    assert result.resolve_status == "unresolved_matrix"
