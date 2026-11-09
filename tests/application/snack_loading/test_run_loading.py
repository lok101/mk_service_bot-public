from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.application.matrix_automation.loading_policy import DefaultMatrixCellLoadingPolicy
from src.application.snack_loading.loading_plan import SnackLoadingCellInput
from src.application.snack_loading.ports import SnackStoreResolveError
from src.application.snack_loading.run_loading import (
    LoadingBatchInput,
    RunSnackLoading,
)
from src.domain.snack_loading import SnackMachineStock
from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore

_MACHINE = "501"
_AS_OF = datetime(2026, 7, 1, tzinfo=UTC)


@dataclass(slots=True)
class _FakeCatalogSync:
    calls: int = 0

    def sync(self) -> None:
        self.calls += 1


@dataclass(slots=True)
class _FakeMoveClient:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail_codes: set[str] = field(default_factory=set)
    store_resolve_codes: set[str] = field(default_factory=set)

    def create_move(
        self,
        *,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        self.calls.append({"machine_code": machine_code, "positions": list(positions)})
        if machine_code in self.store_resolve_codes:
            raise SnackStoreResolveError(f"store {machine_code} outside WAREHOUSES_PATH")
        if machine_code in self.fail_codes:
            msg = f"ms fail for {machine_code}"
            raise RuntimeError(msg)
        return f"move-{machine_code}"


@dataclass(slots=True)
class _FakeCellSource:
    cells_by_machine: dict[str, tuple[SnackLoadingCellInput, ...]] = field(default_factory=dict)

    def list_plan_cells(self, machine_code: str) -> Sequence[SnackLoadingCellInput]:
        return self.cells_by_machine.get(machine_code, ())


@dataclass(slots=True)
class _FakeMainStock:
    available: dict[str, Decimal] = field(default_factory=dict)

    def available_by_product(self) -> dict[str, Decimal]:
        return dict(self.available)


@dataclass(slots=True)
class _FakeRunStore:
    records: dict[str, Any] = field(default_factory=dict)

    def get(self, run_id: str) -> Any | None:
        return self.records.get(run_id)

    def save(self, record: Any) -> None:
        self.records[record.run_id] = record


@dataclass(slots=True)
class _FakeAlert:
    calls: list[dict[str, str]] = field(default_factory=list)

    def notify_fail_after_move(
        self,
        *,
        machine_code: str,
        move_id: str,
        run_id: str,
    ) -> None:
        self.calls.append({"machine_code": machine_code, "move_id": move_id, "run_id": run_id})


def _stock_with_inventory(
    machine_code: str = _MACHINE,
    *,
    qty: Decimal = Decimal("3"),
) -> SnackMachineStock:
    stock = SnackMachineStock(machine_code=machine_code)
    stock.apply_inventory(
        as_of=_AS_OF,
        quantities={(machine_code, "SnackA", 1): qty},
        product_by_key={(machine_code, "SnackA", 1): "SKU1"},
        inventory_id="inv-1",
    )
    return stock


def _cell(
    machine_code: str = _MACHINE,
    *,
    product: str = "SKU1",
    capacity: int = 10,
    current: str = "3",
) -> SnackLoadingCellInput:
    return SnackLoadingCellInput(
        machine_code=machine_code,
        logical_matrix_name="SnackA",
        line_number=1,
        product_code=product,
        capacity=capacity,
        current_qty=Decimal(current),
        desired_product=product,
        snapshot_product=product,
    )


def _runner(
    *,
    stock_store: InMemorySnackMachineStockStore,
    catalog_sync: _FakeCatalogSync,
    move_client: _FakeMoveClient | None = None,
    cells: Sequence[SnackLoadingCellInput] = (),
    main: dict[str, Decimal] | None = None,
    run_store: _FakeRunStore | None = None,
    alert: _FakeAlert | None = None,
) -> RunSnackLoading:
    return RunSnackLoading(
        stock_store=stock_store,
        catalog_sync=catalog_sync,
        cell_source=_FakeCellSource(cells_by_machine={_MACHINE: tuple(cells)}),
        main_stock=_FakeMainStock(available=main or {"SKU1": Decimal("100")}),
        move_client=move_client or _FakeMoveClient(),
        run_store=run_store or _FakeRunStore(),
        alert_notifier=alert or _FakeAlert(),
        loading_policy=DefaultMatrixCellLoadingPolicy(),
        min_move_fraction=0.01,
    )


def test_execute_rejects_without_inventory() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(SnackMachineStock(machine_code=_MACHINE))
    move_client = _FakeMoveClient()
    catalog_sync = _FakeCatalogSync()
    runner = _runner(
        stock_store=stock_store,
        catalog_sync=catalog_sync,
        move_client=move_client,
        cells=(_cell(),),
    )

    result = runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=(_MACHINE,), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-1",
    )

    assert len(result.apparatus_results) == 1
    assert result.apparatus_results[0].status == "failed"
    assert result.apparatus_results[0].reason == "no_inventory"
    assert move_client.calls == []
    assert result.exit_code != 0


def test_execute_rejects_apparatus_without_snapshot_cells() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory())
    move_client = _FakeMoveClient()
    runner = _runner(
        stock_store=stock_store,
        catalog_sync=_FakeCatalogSync(),
        move_client=move_client,
        cells=(),
    )

    result = runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=(_MACHINE,), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-no-snap",
    )

    assert result.apparatus_results[0].status == "failed"
    assert result.apparatus_results[0].reason == "no_snapshot"
    assert move_client.calls == []
    assert result.exit_code != 0


def test_run_syncs_sheets_catalog_once() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory())
    catalog_sync = _FakeCatalogSync()
    runner = _runner(
        stock_store=stock_store,
        catalog_sync=catalog_sync,
        cells=(_cell(),),
    )

    runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=(_MACHINE,), strategy="full_to_capacity"),),
        mode="plan_only",
        run_id="run-sync",
    )

    assert catalog_sync.calls == 1


@dataclass(slots=True)
class _FailingSaveStockStore:
    inner: InMemorySnackMachineStockStore
    fail_on_save: bool = False

    def load(self, machine_code: str) -> SnackMachineStock | None:
        return self.inner.load(machine_code)

    def save(self, stock: SnackMachineStock) -> None:
        if self.fail_on_save:
            msg = "domain save failed"
            raise RuntimeError(msg)
        self.inner.save(stock)


@dataclass(slots=True)
class _MultiCellSource:
    cells_by_machine: dict[str, tuple[SnackLoadingCellInput, ...]]

    def list_plan_cells(self, machine_code: str) -> Sequence[SnackLoadingCellInput]:
        return self.cells_by_machine.get(machine_code, ())


def test_execute_ms_fail_continues_batch() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory("A1"))
    stock_store.save(_stock_with_inventory("A2"))
    move_client = _FakeMoveClient(fail_codes={"A1"})
    catalog_sync = _FakeCatalogSync()
    cells = {
        "A1": (_cell("A1", capacity=10, current="0"),),
        "A2": (_cell("A2", capacity=10, current="0"),),
    }
    runner = RunSnackLoading(
        stock_store=stock_store,
        catalog_sync=catalog_sync,
        cell_source=_MultiCellSource(cells_by_machine=cells),
        main_stock=_FakeMainStock(available={"SKU1": Decimal("100")}),
        move_client=move_client,
        run_store=_FakeRunStore(),
        alert_notifier=_FakeAlert(),
        loading_policy=DefaultMatrixCellLoadingPolicy(),
        min_move_fraction=0.01,
    )

    result = runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=("A1", "A2"), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-batch",
    )

    assert [r.machine_code for r in result.apparatus_results] == ["A1", "A2"]
    assert result.apparatus_results[0].status == "failed"
    assert result.apparatus_results[0].reason == "ms_create_move_failed"
    assert result.apparatus_results[1].status == "ok"
    assert result.apparatus_results[1].move_id == "move-A2"
    assert result.exit_code != 0
    assert len(move_client.calls) == 2


def test_resume_after_fail_does_not_create_second_move() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory(qty=Decimal("0")))
    move_client = _FakeMoveClient()
    run_store = _FakeRunStore()
    failing_store = _FailingSaveStockStore(inner=stock_store, fail_on_save=True)
    catalog_sync = _FakeCatalogSync()
    alert = _FakeAlert()
    runner = RunSnackLoading(
        stock_store=failing_store,
        catalog_sync=catalog_sync,
        cell_source=_FakeCellSource(cells_by_machine={_MACHINE: (_cell(current="0"),)}),
        main_stock=_FakeMainStock(available={"SKU1": Decimal("100")}),
        move_client=move_client,
        run_store=run_store,
        alert_notifier=alert,
        loading_policy=DefaultMatrixCellLoadingPolicy(),
        min_move_fraction=0.01,
    )

    first = runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=(_MACHINE,), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-resume",
    )
    assert first.apparatus_results[0].reason == "fail_after_move"
    assert first.stopped_early is True
    assert len(move_client.calls) == 1
    assert alert.calls

    failing_store.fail_on_save = False
    resume = runner.execute(
        batches=(),
        mode="execute",
        run_id="run-resume",
        resume_run_id="run-resume",
    )
    assert resume.exit_code == 0
    assert resume.apparatus_results[0].status == "ok"
    assert len(move_client.calls) == 1
    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(_MACHINE, "SnackA", 1) == Decimal("10")


def test_execute_success_move_then_domain_increment() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory(qty=Decimal("0")))
    move_client = _FakeMoveClient()
    runner = _runner(
        stock_store=stock_store,
        catalog_sync=_FakeCatalogSync(),
        move_client=move_client,
        cells=(_cell(current="0"),),
    )

    result = runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=(_MACHINE,), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-ok",
    )

    assert result.exit_code == 0
    assert result.apparatus_results[0].status == "ok"
    assert result.apparatus_results[0].move_id == "move-501"
    assert len(move_client.calls) == 1
    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(_MACHINE, "SnackA", 1) == Decimal("10")


def test_execute_sleeps_machine_interval_between_apparatuses() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory("A1", qty=Decimal("0")))
    stock_store.save(_stock_with_inventory("A2", qty=Decimal("0")))
    sleeps: list[float] = []
    cells = {
        "A1": (_cell("A1", capacity=10, current="0"),),
        "A2": (_cell("A2", capacity=10, current="0"),),
    }
    runner = RunSnackLoading(
        stock_store=stock_store,
        catalog_sync=_FakeCatalogSync(),
        cell_source=_MultiCellSource(cells_by_machine=cells),
        main_stock=_FakeMainStock(available={"SKU1": Decimal("100")}),
        move_client=_FakeMoveClient(),
        run_store=_FakeRunStore(),
        alert_notifier=_FakeAlert(),
        loading_policy=DefaultMatrixCellLoadingPolicy(),
        min_move_fraction=0.01,
        machine_interval_seconds=10.0,
        batch_gap_seconds=20.0,
        sleeper=sleeps.append,
    )

    runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=("A1", "A2"), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-interval",
    )

    assert sleeps == [10.0]


def test_execute_maps_store_resolve_error_to_no_store_not_ms_fail() -> None:
    stock_store = InMemorySnackMachineStockStore()
    stock_store.save(_stock_with_inventory("A1", qty=Decimal("0")))
    stock_store.save(_stock_with_inventory("A2", qty=Decimal("0")))
    move_client = _FakeMoveClient(store_resolve_codes={"A1"})
    cells = {
        "A1": (_cell("A1", capacity=10, current="0"),),
        "A2": (_cell("A2", capacity=10, current="0"),),
    }
    runner = RunSnackLoading(
        stock_store=stock_store,
        catalog_sync=_FakeCatalogSync(),
        cell_source=_MultiCellSource(cells_by_machine=cells),
        main_stock=_FakeMainStock(available={"SKU1": Decimal("100")}),
        move_client=move_client,
        run_store=_FakeRunStore(),
        alert_notifier=_FakeAlert(),
        loading_policy=DefaultMatrixCellLoadingPolicy(),
        min_move_fraction=0.01,
    )

    result = runner.execute(
        batches=(LoadingBatchInput(apparatus_codes=("A1", "A2"), strategy="full_to_capacity"),),
        mode="execute",
        run_id="run-no-store",
    )

    assert result.apparatus_results[0].status == "failed"
    assert result.apparatus_results[0].reason == "no_store"
    assert result.apparatus_results[1].status == "ok"
    assert result.exit_code != 0
    assert len(move_client.calls) == 2
