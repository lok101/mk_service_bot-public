from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from src.application.machine_operations.ports import EventStore
from src.application.service_visits.ports import MaintenanceOnOperationalDaySnapshot
from src.domain.calendar import operational_day
from src.domain.ids import MachineId
from src.domain.machine_operations.events import MaintenanceCompleted


def replay_find_earliest_for_operational_day(
    event_store: EventStore,
    machine_id: MachineId,
    ops_day: date,
    *,
    timezone: ZoneInfo,
    day_end_hour: int,
) -> MaintenanceOnOperationalDaySnapshot | None:
    earliest: MaintenanceCompleted | None = None
    for event in event_store.get_events_for_machine(machine_id):
        if not isinstance(event, MaintenanceCompleted):
            continue
        if operational_day(event.completed_at, timezone, day_end_hour) != ops_day:
            continue
        if earliest is None or event.completed_at < earliest.completed_at:
            earliest = event
    if earliest is None:
        return None
    return MaintenanceOnOperationalDaySnapshot(
        event_id=earliest.event_id,
        technician_id=earliest.technician_id,
        completed_at=earliest.completed_at,
    )
