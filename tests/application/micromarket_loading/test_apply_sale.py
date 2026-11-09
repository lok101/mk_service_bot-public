from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.master_data import MachineKind
from src.application.micromarket_loading import ApplyMicromarketSaleToStock
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError
from src.domain.micromarket_loading.events import (
    MicromarketSaleDeducted,
    MicromarketStockAnomalyRecorded,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    StaticMachineKindLookup,
)


def _seed(store: InMemoryMicromarketDeviceStockStore) -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    store.save(stock)


class _ConflictOnceStore(InMemoryMicromarketDeviceStockStore):
    def __init__(self) -> None:
        super().__init__()
        self._fails = 1

    def save(self, stock: MicromarketDeviceStock) -> None:
        if self._fails > 0:
            self._fails -= 1
            raise MicromarketStockConcurrencyError(machine_code=stock.machine_code)
        super().save(stock)


class _MidBatchAnomalyConflictStore(InMemoryMicromarketDeviceStockStore):
    """First multi-event save persists only the first pending event, then conflicts."""

    def __init__(self) -> None:
        super().__init__()
        self._partial_done = False

    def save(self, stock: MicromarketDeviceStock) -> None:
        if self._partial_done:
            super().save(stock)
            return
        stream = self._streams.setdefault(stock.machine_code, [])
        if len(stream) != stock.loaded_version:
            raise MicromarketStockConcurrencyError(machine_code=stock.machine_code)
        pending = stock.pull_events()
        if len(pending) < 2:
            stream.extend(pending)
            return
        stream.append(pending[0])
        self._partial_done = True
        raise MicromarketStockConcurrencyError(machine_code=stock.machine_code)


def test_apply_sale_retries_on_stock_conflict() -> None:
    # error then happy
    store = _ConflictOnceStore()
    store._fails = 0
    _seed(store)
    store._fails = 1
    uc = ApplyMicromarketSaleToStock(
        stock_store=store,
        machine_kind_lookup=StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET}),
    )
    result = uc.execute(
        machine_code="701",
        product_code="2311",
        qty=Decimal("3"),
        sale_source_id="s1",
        occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
    )
    assert result.status == "deducted"
    assert store.load("701").qty("2311") == Decimal("7")


def test_apply_sale_oversell_mid_batch_retry_does_not_duplicate_anomaly() -> None:
    # error→happy: anomaly persisted, deduct not; retry must not duplicate anomaly
    store = _MidBatchAnomalyConflictStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("2")},
        inventory_id="inv-1",
    )
    store.save(stock)
    uc = ApplyMicromarketSaleToStock(
        stock_store=store,
        machine_kind_lookup=StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET}),
    )
    result = uc.execute(
        machine_code="701",
        product_code="2311",
        qty=Decimal("5"),
        sale_source_id="s-oversell",
        occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
    )
    assert result.status == "deducted"
    events = store.list_events("701")
    anomalies = [e for e in events if isinstance(e, MicromarketStockAnomalyRecorded)]
    deducts = [e for e in events if isinstance(e, MicromarketSaleDeducted)]
    assert len(anomalies) == 1
    assert anomalies[0].sale_source_id == "s-oversell"
    assert len(deducts) == 1
    assert deducts[0].sale_source_id == "s-oversell"
    assert store.load("701").qty("2311") == Decimal("0")


def test_apply_sale_deducts_qty() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    _seed(store)
    uc = ApplyMicromarketSaleToStock(
        stock_store=store,
        machine_kind_lookup=StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET}),
    )
    result = uc.execute(
        machine_code="701",
        product_code="2311",
        qty=Decimal("3"),
        sale_source_id="s1",
        occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
    )
    assert result.status == "deducted"
    assert store.load("701").qty("2311") == Decimal("7")


def test_apply_sale_idempotent_by_sale_source_id() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    _seed(store)
    uc = ApplyMicromarketSaleToStock(
        stock_store=store,
        machine_kind_lookup=StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET}),
    )
    kwargs = dict(
        machine_code="701",
        product_code="2311",
        qty=Decimal("1"),
        sale_source_id="s-dup",
        occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
    )
    assert uc.execute(**kwargs).status == "deducted"
    assert uc.execute(**kwargs).status == "idempotent_skip"
    assert store.load("701").qty("2311") == Decimal("9")


def test_apply_sale_skips_non_micromarket_kind() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    uc = ApplyMicromarketSaleToStock(
        stock_store=store,
        machine_kind_lookup=StaticMachineKindLookup({"501": MachineKind.SNACK}),
    )
    result = uc.execute(
        machine_code="501",
        product_code="2311",
        qty=Decimal("1"),
        sale_source_id="s2",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert result.status == "skipped_non_micromarket"
    assert store.load("501") is None


def test_apply_sale_skips_when_no_machine_code() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    uc = ApplyMicromarketSaleToStock(
        stock_store=store,
        machine_kind_lookup=StaticMachineKindLookup({}),
    )
    result = uc.execute(
        machine_code="",
        product_code="2311",
        qty=Decimal("1"),
        sale_source_id="s3",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert result.status == "skipped_no_machine_code"
