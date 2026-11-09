from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.application.micromarket_loading.assembly_orders import (
    AssemblyOrderRejected,
    LaunchFromAssemblyOrders,
    ManageMicromarketAssemblyOrders,
)
from src.application.micromarket_loading.launch_loading import LaunchRejected, LoadingDisabled
from src.application.micromarket_loading.warehouse_stock_snapshot import MainWarehouseStockSnapshot
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    DuplicateCatalogCode,
    MicromarketAssemblyOrder,
)
from src.domain.micromarket_loading.order import MicromarketLoadingCycle
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketAssemblyOrderStore,
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_MACHINE = "701"
_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_WH = UUID("00000000-0000-4000-8000-000000000001")


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _FakeLaunch:
    def __init__(self, *, result: object | None = None) -> None:
        self.result = result
        self.calls: list[str] = []

    def execute(self, *, machine_code: str) -> object | None:
        self.calls.append(machine_code)
        return self.result


def _snapshot(qty: str = "10") -> MainWarehouseStockSnapshot:
    return MainWarehouseStockSnapshot(
        warehouse_id=_WH,
        refreshed_at=_NOW,
        qty_by_catalog_code={"SKU-A": Decimal(qty), "SKU-B": Decimal("5")},
    )


def _manage(
    *,
    store: InMemoryMicromarketAssemblyOrderStore | None = None,
    stock: InMemoryMicromarketWarehouseStockSnapshotStore | None = None,
) -> tuple[ManageMicromarketAssemblyOrders, InMemoryMicromarketAssemblyOrderStore]:
    assembly = store or InMemoryMicromarketAssemblyOrderStore()
    snapshot_store = stock or InMemoryMicromarketWarehouseStockSnapshotStore()
    if snapshot_store.get() is None:
        snapshot_store.replace(_snapshot())
    return (
        ManageMicromarketAssemblyOrders(
            store=assembly,
            warehouse_stock=snapshot_stock_or_none(snapshot_store),
            clock=lambda: _NOW,
        ),
        assembly,
    )


def snapshot_stock_or_none(
    store: InMemoryMicromarketWarehouseStockSnapshotStore,
) -> InMemoryMicromarketWarehouseStockSnapshotStore:
    return store


def test_create_reduces_available_via_reservation() -> None:
    manage, store = _manage()
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("3")})
    assert isinstance(created, MicromarketAssemblyOrder)
    assert created.status is AssemblyOrderStatus.OPEN
    assert store.get(created.order_id) is not None


def test_create_rejects_qty_above_available() -> None:
    manage, _ = _manage()
    result = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("99")})
    assert isinstance(result, AssemblyOrderRejected)
    assert result.reason == "qty_above_available"
    assert result.targets == ("SKU-A",)


def test_create_rejects_qty_above_available_lists_all_codes() -> None:
    manage, _ = _manage()
    result = manage.create(
        machine_code=_MACHINE,
        lines={"SKU-A": Decimal("99"), "SKU-B": Decimal("99")},
    )
    assert isinstance(result, AssemblyOrderRejected)
    assert result.reason == "qty_above_available"
    assert result.targets == ("SKU-A", "SKU-B")


def test_second_party_rejects_duplicate_catalog_code() -> None:
    manage, _ = _manage()
    first = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("1")})
    assert isinstance(first, MicromarketAssemblyOrder)
    second = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("1")})
    assert isinstance(second, DuplicateCatalogCode)


def test_multi_party_different_codes_ok() -> None:
    manage, _ = _manage()
    first = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("1")})
    second = manage.create(machine_code=_MACHINE, lines={"SKU-B": Decimal("2")})
    assert isinstance(first, MicromarketAssemblyOrder)
    assert isinstance(second, MicromarketAssemblyOrder)
    open_orders = manage.list_open_for_machine(machine_code=_MACHINE)
    assert len(open_orders) == 2


def test_cancel_removes_reservation() -> None:
    manage, store = _manage()
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("4")})
    assert isinstance(created, MicromarketAssemblyOrder)
    cancelled = manage.cancel(order_id=created.order_id)
    assert isinstance(cancelled, MicromarketAssemblyOrder)
    assert cancelled.status is AssemblyOrderStatus.CANCELLED
    assert store.list_open_for_machine(_MACHINE) == ()


def test_update_replaces_lines_within_available() -> None:
    manage, store = _manage()
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("2")})
    assert isinstance(created, MicromarketAssemblyOrder)
    updated = manage.update(
        order_id=created.order_id,
        lines={"SKU-A": Decimal("4"), "SKU-B": Decimal("1")},
    )
    assert isinstance(updated, MicromarketAssemblyOrder)
    assert {line.catalog_code: line.qty for line in updated.lines} == {
        "SKU-A": Decimal("4"),
        "SKU-B": Decimal("1"),
    }
    assert store.get(created.order_id) is not None


def test_launch_from_assembly_consumes_when_gate_ok() -> None:
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(_snapshot())
    manage, assembly = _manage(stock=stock)
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("2")})
    assert isinstance(created, MicromarketAssemblyOrder)
    cycle_store = _MemoryCycleStore()
    launch = _FakeLaunch(result=None)
    result = LaunchFromAssemblyOrders(
        assembly_store=assembly,
        cycle_store=cycle_store,
        warehouse_stock=stock,
        launch=launch,
    ).execute(machine_code=_MACHINE, actor="curator-42")
    assert result is None
    assert launch.calls == [_MACHINE]
    saved = assembly.get(created.order_id)
    assert saved is not None
    assert saved.status is AssemblyOrderStatus.CONSUMED
    cycle = cycle_store.load(_MACHINE)
    assert cycle is not None
    assert cycle.lines[0].launch_qty == Decimal("2")
    assert cycle.lines[0].product_code == "SKU-A"


def test_launch_from_assembly_defaults_actor_curator() -> None:
    """happy: actor kw defaults to curator and does not break callers."""
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(_snapshot())
    manage, assembly = _manage(stock=stock)
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("1")})
    assert isinstance(created, MicromarketAssemblyOrder)
    result = LaunchFromAssemblyOrders(
        assembly_store=assembly,
        cycle_store=_MemoryCycleStore(),
        warehouse_stock=stock,
        launch=_FakeLaunch(result=None),
    ).execute(machine_code=_MACHINE)
    assert result is None


def test_launch_keeps_orders_when_move_fails() -> None:
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(_snapshot())
    manage, assembly = _manage(stock=stock)
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("1")})
    assert isinstance(created, MicromarketAssemblyOrder)
    launch = _FakeLaunch(result=LaunchRejected(reason="move failed"))
    result = LaunchFromAssemblyOrders(
        assembly_store=assembly,
        cycle_store=_MemoryCycleStore(),
        warehouse_stock=stock,
        launch=launch,
    ).execute(machine_code=_MACHINE)
    assert isinstance(result, LaunchRejected)
    saved = assembly.get(created.order_id)
    assert saved is not None
    assert saved.status is AssemblyOrderStatus.OPEN


def test_launch_disabled_keeps_orders() -> None:
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(_snapshot())
    manage, assembly = _manage(stock=stock)
    created = manage.create(machine_code=_MACHINE, lines={"SKU-A": Decimal("1")})
    assert isinstance(created, MicromarketAssemblyOrder)
    result = LaunchFromAssemblyOrders(
        assembly_store=assembly,
        cycle_store=_MemoryCycleStore(),
        warehouse_stock=stock,
        launch=_FakeLaunch(result=LoadingDisabled(message="off")),
    ).execute(machine_code=_MACHINE)
    assert isinstance(result, LoadingDisabled)
    assert assembly.get(created.order_id) is not None
    assert assembly.get(created.order_id).status is AssemblyOrderStatus.OPEN  # type: ignore[union-attr]


def test_launch_empty_session_rejected() -> None:
    stock = InMemoryMicromarketWarehouseStockSnapshotStore()
    stock.replace(_snapshot())
    result = LaunchFromAssemblyOrders(
        assembly_store=InMemoryMicromarketAssemblyOrderStore(),
        cycle_store=_MemoryCycleStore(),
        warehouse_stock=stock,
        launch=_FakeLaunch(),
    ).execute(machine_code=_MACHINE)
    assert isinstance(result, AssemblyOrderRejected)
    assert result.reason == "empty_session"
