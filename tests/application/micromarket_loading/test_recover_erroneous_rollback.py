from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.recover_erroneous_rollback import (
    RecoverErroneousRollbackRejected,
    RecoverErroneousRollbackResult,
    RecoverMicromarketLoadingAfterErroneousRollback,
)
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_ORDER = "19571040-2007-49f8-a34a-4613621fda1e"
_AT = datetime(2026, 10, 22, 7, 45, 37, tzinfo=UTC)
_TZ = ZoneInfo("Europe/Moscow")


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}
        self._opened: dict[tuple[str, str], object] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        from src.domain.micromarket_loading.order_events import OrderOpened

        for event in cycle.pull_events():
            if isinstance(event, OrderOpened):
                self._opened[(cycle.machine_code, event.order_id)] = event
        self.cycles[cycle.machine_code] = cycle

    def find_opened(self, *, machine_code: str, order_id: str):
        opened = self._opened.get((machine_code, order_id))
        return opened


def _line(*, launch: str) -> DraftLine:
    return DraftLine(
        product_code="d-4",
        target_qty=6,
        stock_qty=Decimal("1"),
        need_qty=Decimal("5"),
        launch_qty=Decimal(launch),
    )


def _seed_open_cycle(store: _MemoryCycleStore) -> None:
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft((_line(launch="4"),))
    cycle.record_launch_intent(order_id=_ORDER)
    cycle.open_order(
        order_id=_ORDER,
        move_id="move-1",
        lines=cycle.lines,
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(cycle)


def test_recovers_warehouse_and_device_stock() -> None:
    cycle_store = _MemoryCycleStore()
    _seed_open_cycle(cycle_store)
    cycle = cycle_store.load("701")
    assert cycle is not None
    cycle.roll_back(at=datetime(2026, 10, 22, 9, 3, 13, tzinfo=UTC))
    cycle_store.save(cycle)

    stock_store = InMemoryMicromarketDeviceStockStore()
    warehouse = InMemoryMicromarketWarehouseStockSnapshotStore()
    warehouse.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=UUID("00000000-0000-0000-0000-000000000001"),
            refreshed_at=_AT,
            qty_by_catalog_code={"d-4": Decimal("96")},
        ),
    )
    warehouse.apply_delta(deltas={"d-4": Decimal("4")})

    recover = RecoverMicromarketLoadingAfterErroneousRollback(
        opened_lookup=cycle_store,
        stock_store=stock_store,
        cycle_store=cycle_store,
        warehouse_stock=warehouse,
        products=None,
    )
    result = recover.execute(machine_code="701", order_id=_ORDER)
    assert isinstance(result, RecoverErroneousRollbackResult)
    assert result.status == "recovered"
    assert result.device_stock_applied is True
    assert result.warehouse_delta_lines == 1

    snap = warehouse.get()
    assert snap is not None
    assert snap.qty_by_catalog_code["d-4"] == Decimal("96")

    stock = stock_store.load("701")
    assert stock is not None
    assert stock.qty("d-4") == Decimal("4")


def test_idempotent_when_loading_run_already_applied() -> None:
    cycle_store = _MemoryCycleStore()
    _seed_open_cycle(cycle_store)
    stock_store = InMemoryMicromarketDeviceStockStore()
    from src.domain.micromarket_loading import MicromarketDeviceStock

    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_loading(
        lines={"d-4": Decimal("4")},
        loading_run_id=_ORDER,
        occurred_at=_AT,
    )
    stock_store.save(stock)

    recover = RecoverMicromarketLoadingAfterErroneousRollback(
        opened_lookup=cycle_store,
        stock_store=stock_store,
        cycle_store=cycle_store,
        warehouse_stock=None,
        products=None,
    )
    result = recover.execute(machine_code="701", order_id=_ORDER)
    assert isinstance(result, RecoverErroneousRollbackResult)
    assert result.status == "already_recovered"


def test_rejected_when_order_unknown() -> None:
    recover = RecoverMicromarketLoadingAfterErroneousRollback(
        opened_lookup=_MemoryCycleStore(),
        stock_store=InMemoryMicromarketDeviceStockStore(),
        products=None,
    )
    result = recover.execute(machine_code="701", order_id=_ORDER)
    assert isinstance(result, RecoverErroneousRollbackRejected)
