from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import EventStore
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    PendingMicromarketInventStore,
)
from src.application.service_visits.models import VisitStatus
from src.application.service_visits.ports import ServiceVisitStore
from src.domain.calendar import operational_day, operational_day_window
from src.domain.ids import MachineId
from src.domain.micromarket_loading.events import MicromarketInventoryAccepted


@beartype
@dataclass(frozen=True, slots=True)
class EventStoreVisitFinalizedForDay:
    """VisitFinalizedForDayPort: invent freeze / VisitTask / MC.

    ADR-0096: Accept invent freezes further ``now`` for the ops day without
    completing VisitTask (pending, then applied invent on stock after squeeze).
    Completed VisitTask and MaintenanceCompleted remain freeze signals.
    """

    event_store: EventStore
    timezone: ZoneInfo
    day_end_hour: int
    visit_store: ServiceVisitStore | None = None
    pending_store: PendingMicromarketInventStore | None = None
    stock_store: MicromarketDeviceStockStore | None = None

    @beartype
    def is_finalized(self, machine_code: str, checked_at: datetime) -> bool:
        ops_day = operational_day(checked_at, self.timezone, self.day_end_hour)
        if self.pending_store is not None:
            pending = self.pending_store.get_for_machine(machine_code)
            if pending is not None and pending.operational_day == ops_day:
                return True
        if self.stock_store is not None:
            for event in self.stock_store.list_events(machine_code):
                if not isinstance(event, MicromarketInventoryAccepted):
                    continue
                if operational_day(event.as_of, self.timezone, self.day_end_hour) == ops_day:
                    return True
        if self.visit_store is not None:
            completed = self.visit_store.list_for_machine(
                MachineId(machine_code),
                status=VisitStatus.COMPLETED,
            )
            if any(visit.due_date == ops_day for visit in completed):
                return True
        start, end = operational_day_window(ops_day, self.timezone, self.day_end_hour)
        events = self.event_store.list_maintenance_completed_in_completed_at_window(
            MachineId(machine_code),
            completed_at_start_inclusive=start,
            completed_at_end_exclusive=end,
        )
        return bool(events)
