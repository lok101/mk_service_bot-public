from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import EventStore
from src.application.service_visits.ports import MaintenanceOnOperationalDaySnapshot
from src.domain.calendar import operational_day_window
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class EventStoreMaintenanceOnOperationalDayLookup:
    event_store: EventStore

    @beartype
    def find_earliest_for_operational_day(
        self,
        machine_id: MachineId,
        ops_day: date,
        *,
        timezone: ZoneInfo,
        day_end_hour: int,
    ) -> MaintenanceOnOperationalDaySnapshot | None:
        start, end = operational_day_window(ops_day, timezone, day_end_hour)
        events = self.event_store.list_maintenance_completed_in_completed_at_window(
            machine_id,
            completed_at_start_inclusive=start,
            completed_at_end_exclusive=end,
        )
        if not events:
            return None
        earliest = events[0]
        return MaintenanceOnOperationalDaySnapshot(
            event_id=earliest.event_id,
            technician_id=earliest.technician_id,
            completed_at=earliest.completed_at,
        )
