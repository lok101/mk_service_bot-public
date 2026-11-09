from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.calendar import operational_day
from src.domain.micromarket_loading.order_errors import SecondCommandRejected
from src.domain.micromarket_loading.order_events import (
    OPS_CONFIRMED_WITHOUT_RECOUNT,
    DraftSaved,
    MicromarketLoadingCycleEvent,
    OrderAlertRecorded,
    OrderClosed,
    OrderLaunchIntended,
    OrderMoveRepaired,
    OrderOpened,
    OrderRecounted,
    OrderRecountReplaced,
    OrderRolledBack,
    OrderVisitLinked,
)
from src.domain.micromarket_loading.order_events import (
    DraftLine as DraftLine,
)


class OrderStatus(StrEnum):
    OPEN = "open"
    RECOUNTED = "recounted"
    CLOSED = "closed"
    ROLLED_BACK = "rolled_back"


@beartype
@dataclass(slots=True)
class MicromarketLoadingCycle:
    machine_code: str
    status: OrderStatus | None = None
    order_id: str | None = None
    move_id: str | None = None
    visit_id: str | None = None
    lines: tuple[DraftLine, ...] = ()
    opened_operational_day: date | None = None
    opened_at: datetime | None = None
    reopen_blocked_day: date | None = None
    deltas: tuple[tuple[str, Decimal], ...] = ()
    shelf_before: tuple[tuple[str, Decimal], ...] | None = None
    close_kind: str | None = None
    alerted_days: frozenset[tuple[str, date]] = field(default_factory=frozenset)
    _pending: list[MicromarketLoadingCycleEvent] = field(default_factory=list, repr=False)
    _loaded_version: int = field(default=0, repr=False)

    @property
    @beartype
    def loaded_version(self) -> int:
        return self._loaded_version

    @beartype
    def pull_events(self) -> tuple[MicromarketLoadingCycleEvent, ...]:
        events = tuple(self._pending)
        self._pending.clear()
        return events

    @beartype
    def mark_persisted(self, *, stream_version: int) -> None:
        if stream_version < self._loaded_version:
            raise ValueError("stream_version must not decrease")
        self._loaded_version = stream_version

    @classmethod
    @beartype
    def rehydrate(
        cls,
        *,
        machine_code: str,
        events: Iterable[MicromarketLoadingCycleEvent],
        loaded_version: int | None = None,
    ) -> MicromarketLoadingCycle:
        events_tuple = tuple(events)
        cycle = cls(machine_code=machine_code)
        for event in events_tuple:
            cycle._apply(event)
        cycle._pending.clear()
        cycle._loaded_version = len(events_tuple) if loaded_version is None else loaded_version
        return cycle

    @beartype
    def save_draft(self, lines: tuple[DraftLine, ...]) -> None:
        event = DraftSaved(lines=lines)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def record_launch_intent(self, *, order_id: str) -> None:
        if self.status in (OrderStatus.OPEN, OrderStatus.RECOUNTED):
            raise SecondCommandRejected()
        event = OrderLaunchIntended(order_id=order_id)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def open_order(
        self,
        *,
        order_id: str,
        move_id: str,
        lines: tuple[DraftLine, ...],
        opened_at: datetime,
        timezone: ZoneInfo,
        day_end_hour: int,
    ) -> None:
        if self.status in (OrderStatus.OPEN, OrderStatus.RECOUNTED):
            raise SecondCommandRejected()
        day = operational_day(opened_at, timezone, day_end_hour)
        if self.reopen_blocked_day is not None and self.reopen_blocked_day == day:
            raise SecondCommandRejected()
        event = OrderOpened(
            order_id=order_id,
            move_id=move_id,
            lines=lines,
            opened_at=opened_at,
            opened_operational_day=day,
        )
        self._apply(event)
        self._pending.append(event)

    @beartype
    def mark_recounted(
        self,
        *,
        at: datetime,
        deltas: tuple[tuple[str, Decimal], ...],
        shelf_before: tuple[tuple[str, Decimal], ...],
    ) -> None:
        if self.status is not OrderStatus.OPEN:
            raise ValueError("mark_recounted requires open order")
        event = OrderRecounted(deltas=deltas, at=at, shelf_before=shelf_before)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def replace_recount_deltas(
        self,
        *,
        at: datetime,
        deltas: tuple[tuple[str, Decimal], ...],
    ) -> None:
        if self.status is not OrderStatus.RECOUNTED:
            raise ValueError("replace_recount_deltas requires recounted order")
        if self.shelf_before is None or len(self.shelf_before) == 0:
            raise ValueError("replace_recount_deltas requires shelf_before baseline")
        event = OrderRecountReplaced(deltas=deltas, at=at)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def close(self, *, at: datetime) -> None:
        if self.status is OrderStatus.CLOSED:
            return
        if self.status is not OrderStatus.RECOUNTED:
            raise ValueError("close requires recounted order")
        event = OrderClosed(at=at)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def close_without_recount(self, *, at: datetime) -> None:
        if self.status is OrderStatus.CLOSED and self.close_kind == OPS_CONFIRMED_WITHOUT_RECOUNT:
            return
        if self.status is not OrderStatus.OPEN:
            raise ValueError("close_without_recount requires open order")
        event = OrderClosed(at=at, close_kind=OPS_CONFIRMED_WITHOUT_RECOUNT)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def roll_back(self, *, at: datetime) -> None:
        if self.status is not OrderStatus.OPEN:
            raise ValueError("roll_back requires open order")
        event = OrderRolledBack(at=at)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def was_alerted(self, *, order_id: str, operational_day: date) -> bool:
        return (order_id, operational_day) in self.alerted_days

    @beartype
    def record_alert(self, *, order_id: str, operational_day: date) -> None:
        if self.was_alerted(order_id=order_id, operational_day=operational_day):
            return
        event = OrderAlertRecorded(order_id=order_id, operational_day=operational_day)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def repair_move_id(self, *, move_id: str) -> None:
        if self.status is not OrderStatus.OPEN:
            raise ValueError("repair_move_id requires open order")
        if not move_id.strip():
            raise ValueError("repair_move_id requires non-empty move_id")
        if self.move_id == move_id:
            return
        event = OrderMoveRepaired(move_id=move_id)
        self._apply(event)
        self._pending.append(event)

    @beartype
    def link_visit(self, visit_id: str) -> None:
        if self.visit_id == visit_id:
            return
        if self.visit_id is not None:
            raise ValueError(
                f"visit_id already linked to {self.visit_id!r}; cannot relink to {visit_id!r}"
            )
        event = OrderVisitLinked(visit_id=visit_id)
        self._apply(event)
        self._pending.append(event)

    def _apply(self, event: MicromarketLoadingCycleEvent) -> None:
        if isinstance(event, DraftSaved):
            self.lines = event.lines
            # Fresh draft after terminal cycle: UI must honour launch_qty (ISS-404
            # only skips stale closed/rolled_back lines, not a new DraftSaved).
            if self.status in (OrderStatus.CLOSED, OrderStatus.ROLLED_BACK):
                self.status = None
                # New operational cycle must not reuse MS externalCode / move id.
                self.order_id = None
                self.move_id = None
                self.visit_id = None
                self.opened_at = None
            return
        if isinstance(event, OrderLaunchIntended):
            self.order_id = event.order_id
            return
        if isinstance(event, OrderOpened):
            self.status = OrderStatus.OPEN
            self.order_id = event.order_id
            self.move_id = event.move_id
            self.lines = event.lines
            self.opened_operational_day = event.opened_operational_day
            self.opened_at = event.opened_at
            self.reopen_blocked_day = None
            self.visit_id = None
            self.deltas = ()
            self.shelf_before = None
            self.close_kind = None
            return
        if isinstance(event, OrderRecounted):
            self.status = OrderStatus.RECOUNTED
            self.deltas = event.deltas
            self.shelf_before = event.shelf_before
            return
        if isinstance(event, OrderRecountReplaced):
            self.deltas = event.deltas
            return
        if isinstance(event, OrderClosed):
            self.status = OrderStatus.CLOSED
            self.close_kind = event.close_kind
            self.reopen_blocked_day = self.opened_operational_day
            self.opened_at = None
            return
        if isinstance(event, OrderRolledBack):
            self.status = OrderStatus.ROLLED_BACK
            self.visit_id = None
            self.opened_at = None
            return
        if isinstance(event, OrderAlertRecorded):
            self.alerted_days = self.alerted_days | {
                (event.order_id, event.operational_day),
            }
            return
        if isinstance(event, OrderVisitLinked):
            self.visit_id = event.visit_id
            return
        if isinstance(event, OrderMoveRepaired):
            self.move_id = event.move_id
            return
