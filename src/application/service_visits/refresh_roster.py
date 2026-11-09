from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.materialize import (
    MachineSchedule,
    MaterializeScheduledVisits,
)
from src.application.service_visits.models import VisitKind, VisitStatus
from src.application.service_visits.ports import (
    MaintenanceOnOperationalDayLookup,
    ServiceVisitStore,
)
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.calendar import operational_day
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class RosterWeekdayChange:
    machine_id: MachineId
    service_weekdays: frozenset[int]


@beartype
@dataclass(frozen=True, slots=True)
class RefreshRosterResult:
    upserted: int = 0
    cancelled: int = 0
    retrospectively_closed: int = 0


@beartype
def cancel_open_scheduled_for_machines(
    store: ServiceVisitStore,
    *,
    machine_ids: tuple[MachineId, ...],
    ops_day: date,
) -> int:
    cancelled = 0
    for machine_id in machine_ids:
        visit_id = scheduled_visit_id(machine_id, ops_day)
        existing = store.get(visit_id)
        if (
            existing is not None
            and existing.kind is VisitKind.SCHEDULED
            and existing.status is VisitStatus.OPEN
        ):
            store.delete(visit_id)
            cancelled += 1
    return cancelled


@beartype
def cancel_open_scheduled_outside_weekdays(
    store: ServiceVisitStore,
    *,
    machine_id: MachineId,
    service_weekdays: frozenset[int],
) -> int:
    """Delete open scheduled whose due weekday is no longer in the machine roster."""
    cancelled = 0
    for visit in store.list_for_machine(machine_id, status=VisitStatus.OPEN):
        if visit.kind is not VisitKind.SCHEDULED:
            continue
        if visit.due_date.weekday() in service_weekdays:
            continue
        store.delete(visit.visit_id)
        cancelled += 1
    return cancelled


@beartype
class RefreshScheduledVisitsForRosterChange:
    def __init__(
        self,
        *,
        store: ServiceVisitStore,
        maintenance_lookup: MaintenanceOnOperationalDayLookup,
        timezone: ZoneInfo,
        day_end_hour: int,
    ) -> None:
        self._store = store
        self._maintenance_lookup = maintenance_lookup
        self._timezone = timezone
        self._day_end_hour = day_end_hour

    @beartype
    def execute(
        self,
        *,
        changes: tuple[RosterWeekdayChange, ...],
        now: datetime,
        timezone: ZoneInfo,
        day_end_hour: int,
        unassigned_machine_ids: tuple[MachineId, ...] = (),
    ) -> RefreshRosterResult:
        ops_day = operational_day(now, timezone, day_end_hour)
        upserted = 0
        cancelled = 0
        retrospectively_closed = 0
        materialize = MaterializeScheduledVisits(
            store=self._store,
            maintenance_lookup=self._maintenance_lookup,
            timezone=self._timezone,
            day_end_hour=self._day_end_hour,
        )
        for change in changes:
            cancelled += cancel_open_scheduled_outside_weekdays(
                self._store,
                machine_id=change.machine_id,
                service_weekdays=change.service_weekdays,
            )
            if ops_day.weekday() in change.service_weekdays:
                part = materialize.execute(
                    due_date=ops_day,
                    catalog=(MachineSchedule(change.machine_id, change.service_weekdays),),
                    now=now,
                )
                upserted += part.upserted
                retrospectively_closed += part.retrospectively_closed
                continue
            visit_id = scheduled_visit_id(change.machine_id, ops_day)
            existing = self._store.get(visit_id)
            if (
                existing is not None
                and existing.kind is VisitKind.SCHEDULED
                and existing.status is VisitStatus.OPEN
            ):
                self._store.delete(visit_id)
                cancelled += 1
        cancelled += cancel_open_scheduled_for_machines(
            self._store,
            machine_ids=unassigned_machine_ids,
            ops_day=ops_day,
        )
        return RefreshRosterResult(
            upserted=upserted,
            cancelled=cancelled,
            retrospectively_closed=retrospectively_closed,
        )
