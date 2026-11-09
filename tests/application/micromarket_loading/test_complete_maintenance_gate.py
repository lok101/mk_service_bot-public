from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.master_data import MachineKind
from src.application.micromarket_loading.complete_maintenance_gate import (
    MICROMARKET_INVENTORY_REQUIRED_REASON,
    MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
    MicromarketCompleteMaintenanceInventoryGate,
)
from src.domain.ids import MachineId
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    StaticMachineKindLookup,
)

_MACHINE = MachineId("701")
_TZ = ZoneInfo("UTC")
_DAY_END = 4
_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
_ORDER_AT = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


def _draft_line() -> DraftLine:
    return DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )


def _open_cycle(store: _MemoryCycleStore) -> MicromarketLoadingCycle:
    cycle = MicromarketLoadingCycle(machine_code=_MACHINE.value)
    cycle.open_order(
        order_id="order-701",
        move_id="move-701",
        lines=(_draft_line(),),
        opened_at=_ORDER_AT,
        timezone=_TZ,
        day_end_hour=_DAY_END,
    )
    store.save(cycle)
    return cycle


def _recounted_cycle(store: _MemoryCycleStore) -> MicromarketLoadingCycle:
    cycle = _open_cycle(store)
    cycle.mark_recounted(
        at=_ORDER_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    store.save(cycle)
    return cycle


def _gate(
    *,
    kind: MachineKind = MachineKind.MICRO_MARKET,
    store: InMemoryMicromarketDeviceStockStore | None = None,
    order_store: _MemoryCycleStore | None = None,
) -> tuple[MicromarketCompleteMaintenanceInventoryGate, InMemoryMicromarketDeviceStockStore]:
    stock = store or InMemoryMicromarketDeviceStockStore()
    return (
        MicromarketCompleteMaintenanceInventoryGate(
            kind_lookup=StaticMachineKindLookup({_MACHINE.value: kind}),
            stock_store=stock,
            timezone=_TZ,
            day_end_hour=_DAY_END,
            order_store=order_store,
        ),
        stock,
    )


def test_complete_maintenance_blocked_without_micromarket_inventory_today() -> None:
    gate, _store = _gate()
    reason = gate.complete_maintenance_block_reason(_MACHINE, _NOW)
    assert reason == MICROMARKET_INVENTORY_REQUIRED_REASON


def test_complete_maintenance_allowed_with_micromarket_inventory_today() -> None:
    gate, store = _gate()
    stock = MicromarketDeviceStock(machine_code=_MACHINE.value)
    stock.apply_inventory(
        as_of=_NOW,
        quantities={"2311": Decimal("1")},
        inventory_id="inv-1",
    )
    store.save(stock)

    assert gate.complete_maintenance_block_reason(_MACHINE, _NOW) is None


def test_coffee_complete_maintenance_unaffected() -> None:
    gate, _store = _gate(kind=MachineKind.COFFEE)
    assert gate.complete_maintenance_block_reason(_MACHINE, _NOW) is None
    assert gate.suppress_coffee_revision(_MACHINE) is False


def test_loading_photos_blocked_when_order_open() -> None:
    # error: photos blocked while micromarket order is open
    order_store = _MemoryCycleStore()
    _open_cycle(order_store)
    gate, _stock = _gate(order_store=order_store)
    assert (
        gate.loading_photos_block_reason(_MACHINE, _NOW) == MICROMARKET_LOADING_PHOTOS_OPEN_REASON
    )


def test_complete_maintenance_blocked_when_order_open_after_inventory() -> None:
    # edge: visit final blocked while order open (same reason as photos)
    order_store = _MemoryCycleStore()
    _open_cycle(order_store)
    gate, store = _gate(order_store=order_store)
    stock = MicromarketDeviceStock(machine_code=_MACHINE.value)
    stock.apply_inventory(
        as_of=_NOW,
        quantities={"2311": Decimal("1")},
        inventory_id="inv-open",
    )
    store.save(stock)
    assert (
        gate.complete_maintenance_block_reason(_MACHINE, _NOW)
        == MICROMARKET_LOADING_PHOTOS_OPEN_REASON
    )


def test_complete_maintenance_inventory_reason_before_open() -> None:
    # edge: missing inventory still wins over open-order gate
    order_store = _MemoryCycleStore()
    _open_cycle(order_store)
    gate, _stock = _gate(order_store=order_store)
    assert gate.complete_maintenance_block_reason(_MACHINE, _NOW) == (
        MICROMARKET_INVENTORY_REQUIRED_REASON
    )


def test_loading_photos_close_recounted_order() -> None:
    # happy: visit final close recounted micromarket order
    order_store = _MemoryCycleStore()
    _recounted_cycle(order_store)
    gate, _stock = _gate(order_store=order_store)
    assert gate.loading_photos_block_reason(_MACHINE, _NOW) is None
    gate.close_loading_order_after_visit_final(_MACHINE)
    cycle = order_store.load(_MACHINE.value)
    assert cycle is not None
    assert cycle.status is OrderStatus.CLOSED


def test_loading_photos_close_is_idempotent_when_already_closed() -> None:
    # edge: second close on already closed order is a no-op
    order_store = _MemoryCycleStore()
    cycle = _recounted_cycle(order_store)
    cycle.close(at=_ORDER_AT)
    order_store.save(cycle)
    gate, _stock = _gate(order_store=order_store)
    gate.close_loading_order_after_visit_final(_MACHINE)
    gate.close_loading_order_after_visit_final(_MACHINE)
    closed = order_store.load(_MACHINE.value)
    assert closed is not None
    assert closed.status is OrderStatus.CLOSED


def test_loading_photos_gate_skips_non_micromarket() -> None:
    # edge: coffee kind ignores open order for photos gate
    order_store = _MemoryCycleStore()
    _open_cycle(order_store)
    gate, _stock = _gate(kind=MachineKind.COFFEE, order_store=order_store)
    assert gate.loading_photos_block_reason(_MACHINE, _NOW) is None
    gate.close_loading_order_after_visit_final(_MACHINE)
    cycle = order_store.load(_MACHINE.value)
    assert cycle is not None
    assert cycle.status is OrderStatus.OPEN


def test_invent_gate_allows_complete_when_order_closed() -> None:
    """happy: terminal order (ops-accept) unblocks complete without invent today."""
    order_store = _MemoryCycleStore()
    cycle = _open_cycle(order_store)
    cycle.close_without_recount(at=_ORDER_AT)
    order_store.save(cycle)
    gate, _stock = _gate(order_store=order_store)
    assert gate.complete_maintenance_block_reason(_MACHINE, _NOW) is None
    assert gate.loading_photos_block_reason(_MACHINE, _NOW) is None


def test_open_order_still_blocks_complete_without_invent() -> None:
    """error: open order still requires invent (inventory reason wins)."""
    order_store = _MemoryCycleStore()
    _open_cycle(order_store)
    gate, _stock = _gate(order_store=order_store)
    assert (
        gate.complete_maintenance_block_reason(_MACHINE, _NOW)
        == MICROMARKET_INVENTORY_REQUIRED_REASON
    )
