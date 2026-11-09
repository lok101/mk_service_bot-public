from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.models import (
    CloseType,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.ports import ServiceVisitStore
from src.application.service_visits.visit_ids import ad_hoc_visit_id
from src.domain.calendar import operational_day
from src.domain.ids import EventId, MachineId, TechnicianId


@beartype
class CloseServiceVisit:
    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    def execute(
        self,
        *,
        machine_id: MachineId,
        technician_id: TechnicianId,
        maintenance_event_id: EventId,
        completed_at: datetime,
        service_weekdays: frozenset[int],
        timezone: ZoneInfo,
        day_end_hour: int,
        now: datetime,
    ) -> None:
        if self._already_closed(machine_id, maintenance_event_id):
            return
        ops_day = operational_day(completed_at, timezone, day_end_hour)
        open_visits = self._store.list_for_machine(machine_id, status=VisitStatus.OPEN)
        closable_extra = next(
            (
                visit
                for visit in open_visits
                if visit.kind is VisitKind.EXTRA_INCIDENT and visit.closable
            ),
            None,
        )
        if closable_extra is not None:
            self._complete(
                closable_extra,
                close_type=CloseType.EXTRA_INCIDENT,
                technician_id=technician_id,
                maintenance_event_id=maintenance_event_id,
                completed_at=completed_at,
                now=now,
            )
            self._mark_open_scheduled_missed(machine_id, now)
            return
        closable_scheduled = next(
            (
                visit
                for visit in open_visits
                if visit.kind is VisitKind.SCHEDULED and visit.closable
            ),
            None,
        )
        if closable_scheduled is not None:
            self._complete(
                closable_scheduled,
                close_type=CloseType.SCHEDULED,
                technician_id=technician_id,
                maintenance_event_id=maintenance_event_id,
                completed_at=completed_at,
                now=now,
            )
            self._mark_open_scheduled_missed(machine_id, now)
            return
        self._upsert_ad_hoc(
            machine_id=machine_id,
            technician_id=technician_id,
            maintenance_event_id=maintenance_event_id,
            completed_at=completed_at,
            service_weekdays=service_weekdays,
            ops_day=ops_day,
            now=now,
        )
        # Early / spontaneous TO: clear leftover open scheduled so list has no
        # false overdue (ISS-368); same as after completing a closable slot.
        self._mark_open_scheduled_missed(machine_id, now)

    def _already_closed(self, machine_id: MachineId, maintenance_event_id: EventId) -> bool:
        return any(
            visit.maintenance_event_id == maintenance_event_id
            and visit.status is VisitStatus.COMPLETED
            for visit in self._store.list_for_machine(machine_id)
        )

    def _complete(
        self,
        visit: ServiceVisit,
        *,
        close_type: CloseType,
        technician_id: TechnicianId,
        maintenance_event_id: EventId,
        completed_at: datetime,
        now: datetime,
    ) -> None:
        self._store.upsert(
            replace(
                visit,
                status=VisitStatus.COMPLETED,
                closable=False,
                priority_boost=False,
                close_type=close_type,
                completed_at=completed_at,
                completed_by_technician_id=technician_id,
                maintenance_event_id=maintenance_event_id,
                updated_at=now,
            )
        )

    def _mark_open_scheduled_missed(self, machine_id: MachineId, now: datetime) -> None:
        for visit in self._store.list_for_machine(machine_id, status=VisitStatus.OPEN):
            if visit.kind is not VisitKind.SCHEDULED:
                continue
            self._store.upsert(
                replace(
                    visit,
                    status=VisitStatus.MISSED,
                    closable=False,
                    priority_boost=False,
                    updated_at=now,
                )
            )

    def _upsert_ad_hoc(
        self,
        *,
        machine_id: MachineId,
        technician_id: TechnicianId,
        maintenance_event_id: EventId,
        completed_at: datetime,
        service_weekdays: frozenset[int],
        ops_day: date,
        now: datetime,
    ) -> None:
        visit_id = ad_hoc_visit_id(machine_id, ops_day, maintenance_event_id)
        if self._store.get(visit_id) is not None:
            return
        close_type = CloseType.UNSCHEDULED_ROSTER if not service_weekdays else CloseType.SPONTANEOUS
        self._store.upsert(
            ServiceVisit(
                visit_id=visit_id,
                machine_id=machine_id,
                kind=VisitKind.SCHEDULED,
                due_date=ops_day,
                status=VisitStatus.COMPLETED,
                closable=False,
                priority_boost=False,
                incident_source=None,
                close_type=close_type,
                completed_at=completed_at,
                completed_by_technician_id=technician_id,
                maintenance_event_id=maintenance_event_id,
                created_at=now,
                updated_at=now,
            )
        )
