from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.alert_sweep import SweepMicromarketLoadingAlerts
from src.domain.micromarket_loading.order import (
    DraftLine,
    MicromarketLoadingCycle,
    OrderStatus,
)

_TZ = ZoneInfo("Europe/Moscow")
_HOUR = 6
_MACHINE = "701"
_NAME = "Офис"
_ORDER = "order-1"


class _FakeAlerter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


class _FakeNames:
    def display_name(self, machine_code: str) -> str:
        if machine_code == _MACHINE:
            return _NAME
        return machine_code


class _FakeStore:
    def __init__(self) -> None:
        self._cycles: dict[str, MicromarketLoadingCycle] = {}

    def list_cycles(self) -> tuple[MicromarketLoadingCycle, ...]:
        return tuple(self._cycles.values())

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        cycle.pull_events()
        self._cycles[cycle.machine_code] = cycle

    def put(self, cycle: MicromarketLoadingCycle) -> None:
        self._cycles[cycle.machine_code] = cycle


def _line() -> DraftLine:
    return DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )


def _open_cycle(*, at: datetime, status: OrderStatus = OrderStatus.OPEN) -> MicromarketLoadingCycle:
    cycle = MicromarketLoadingCycle(machine_code=_MACHINE)
    cycle.open_order(
        order_id=_ORDER,
        move_id="move-1",
        lines=(_line(),),
        opened_at=at,
        timezone=_TZ,
        day_end_hour=_HOUR,
    )
    cycle.pull_events()
    if status is OrderStatus.RECOUNTED:
        cycle.mark_recounted(
            at=at,
            deltas=(("2311", Decimal("-1")),),
            shelf_before=(("2311", Decimal("1")),),
        )
        cycle.pull_events()
    elif status is OrderStatus.CLOSED:
        cycle.mark_recounted(
            at=at,
            deltas=(("2311", Decimal("-1")),),
            shelf_before=(("2311", Decimal("1")),),
        )
        cycle.close(at=at)
        cycle.pull_events()
    elif status is OrderStatus.ROLLED_BACK:
        cycle.roll_back(at=at)
        cycle.pull_events()
    return cycle


def _sweep(store: _FakeStore, alerter: _FakeAlerter) -> SweepMicromarketLoadingAlerts:
    return SweepMicromarketLoadingAlerts(
        cycle_store=store,
        alerter=alerter,
        names=_FakeNames(),
        timezone=_TZ,
        day_end_hour=_HOUR,
    )


def test_open_and_recounted_orders_are_not_alerted() -> None:
    store = _FakeStore()
    at = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)
    store.put(_open_cycle(at=at, status=OrderStatus.OPEN))
    recounted = MicromarketLoadingCycle(machine_code="702")
    recounted.open_order(
        order_id="order-2",
        move_id="move-2",
        lines=(_line(),),
        opened_at=at,
        timezone=_TZ,
        day_end_hour=_HOUR,
    )
    recounted.mark_recounted(
        at=at,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    recounted.pull_events()
    store.put(recounted)
    alerter = _FakeAlerter()
    sweep = _sweep(store, alerter)

    sweep.sweep_once(at)
    sweep.sweep_once(datetime(2026, 9, 25, 10, 0, tzinfo=_TZ))

    assert alerter.messages == []


def test_closed_order_is_not_alerted() -> None:
    at = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)
    closed = _open_cycle(at=at, status=OrderStatus.CLOSED)
    rolled = MicromarketLoadingCycle(machine_code="702")
    rolled.open_order(
        order_id="order-2",
        move_id="move-2",
        lines=(_line(),),
        opened_at=at,
        timezone=_TZ,
        day_end_hour=_HOUR,
    )
    rolled.roll_back(at=at)
    rolled.pull_events()
    store = _FakeStore()
    store.put(closed)
    store.put(rolled)
    alerter = _FakeAlerter()

    _sweep(store, alerter).sweep_once(at)

    assert alerter.messages == []


def test_alert_worker_interval_is_one_hour() -> None:
    from src.infrastructure.micromarket_loading_alert_worker import SWEEP_INTERVAL_SECONDS

    assert SWEEP_INTERVAL_SECONDS == 60 * 60
