from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.models import (
    CloseType,
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
    VisitTaskSource,
)
from src.application.service_visits.ports import (
    MaintenanceOnOperationalDayLookup,
    ServiceVisitStore,
)
from src.application.service_visits.visit_ids import ad_hoc_visit_id, scheduled_visit_id
from src.domain.ids import MachineId

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class MachineSchedule:
    machine_id: MachineId
    service_weekdays: frozenset[int]


@beartype
@dataclass(frozen=True, slots=True)
class MaterializeResult:
    upserted: int = 0
    buried: int = 0
    extras_absorbed: int = 0
    retrospectively_closed: int = 0


@beartype
class MaterializeScheduledVisits:
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
        due_date: date,
        catalog: tuple[MachineSchedule, ...],
        now: datetime,
    ) -> MaterializeResult:
        upserted = 0
        buried = 0
        extras_absorbed = 0
        retrospectively_closed = 0
        for machine in catalog:
            if due_date.weekday() not in machine.service_weekdays:
                continue
            part = self._materialize_machine(machine=machine, due_date=due_date, now=now)
            upserted += part.upserted
            buried += part.buried
            extras_absorbed += part.extras_absorbed
            retrospectively_closed += part.retrospectively_closed
        return MaterializeResult(
            upserted=upserted,
            buried=buried,
            extras_absorbed=extras_absorbed,
            retrospectively_closed=retrospectively_closed,
        )

    def _materialize_machine(
        self,
        *,
        machine: MachineSchedule,
        due_date: date,
        now: datetime,
    ) -> MaterializeResult:
        visit_id = scheduled_visit_id(machine.machine_id, due_date)
        existing = self._store.get(visit_id)
        priority_boost = existing.priority_boost if existing is not None else False
        merged_sources: frozenset[VisitTaskSource] = (
            existing.sources if existing is not None else frozenset()
        )
        merged_loading_order_id = existing.loading_order_id if existing is not None else None
        created_at = existing.created_at if existing is not None else now
        open_visits = self._store.list_for_machine(
            machine.machine_id,
            status=VisitStatus.OPEN,
        )
        buried = 0
        extras_absorbed = 0
        for visit in open_visits:
            if visit.kind is VisitKind.SCHEDULED and visit.due_date < due_date:
                self._store.upsert(replace(visit, closable=False, updated_at=now))
                buried += 1
            elif visit.kind is VisitKind.EXTRA_INCIDENT:
                self._store.upsert(
                    replace(
                        visit,
                        status=VisitStatus.CLEARED,
                        closable=False,
                        updated_at=now,
                    )
                )
                extras_absorbed += 1
                if visit.incident_source is not IncidentSource.OFFLINE:
                    priority_boost = True
                merged_sources |= visit.sources
                if merged_loading_order_id is None and visit.loading_order_id is not None:
                    merged_loading_order_id = visit.loading_order_id
            elif (
                visit.kind is VisitKind.SCHEDULED
                and visit.due_date == due_date
                and visit.visit_id != visit_id
            ):
                # Coalesce lazy field:/orphan SCHEDULED into roster scheduled id.
                self._store.upsert(
                    replace(
                        visit,
                        status=VisitStatus.CLEARED,
                        closable=False,
                        updated_at=now,
                    )
                )
                extras_absorbed += 1
                merged_sources |= visit.sources
                if merged_loading_order_id is None and visit.loading_order_id is not None:
                    merged_loading_order_id = visit.loading_order_id
                if existing is None and visit.created_at < created_at:
                    created_at = visit.created_at
        maintenance = self._maintenance_lookup.find_earliest_for_operational_day(
            machine.machine_id,
            due_date,
            timezone=self._timezone,
            day_end_hour=self._day_end_hour,
        )
        if maintenance is not None and (existing is None or existing.status is VisitStatus.OPEN):
            slot = ServiceVisit(
                visit_id=visit_id,
                machine_id=machine.machine_id,
                kind=VisitKind.SCHEDULED,
                due_date=due_date,
                status=VisitStatus.COMPLETED,
                closable=False,
                priority_boost=False,
                incident_source=None,
                close_type=CloseType.SCHEDULED,
                completed_at=maintenance.completed_at,
                completed_by_technician_id=maintenance.technician_id,
                maintenance_event_id=maintenance.event_id,
                created_at=created_at,
                updated_at=now,
                sources=merged_sources,
                loading_order_id=merged_loading_order_id,
            )
            self._store.upsert(slot)
            ad_hoc_id = ad_hoc_visit_id(
                machine.machine_id,
                due_date,
                maintenance.event_id,
            )
            if self._store.get(ad_hoc_id) is not None:
                self._store.delete(ad_hoc_id)
            _LOGGER.info(
                "service_visit_retrospective_close",
                extra={
                    "machine_id": str(machine.machine_id),
                    "ops_day": due_date.isoformat(),
                    "maintenance_event_id": str(maintenance.event_id),
                    "trigger": "materialize",
                },
            )
            return MaterializeResult(
                buried=buried,
                extras_absorbed=extras_absorbed,
                retrospectively_closed=1,
            )
        if existing is not None and existing.status is not VisitStatus.OPEN:
            return MaterializeResult(buried=buried, extras_absorbed=extras_absorbed)
        if existing is None:
            slot = ServiceVisit(
                visit_id=visit_id,
                machine_id=machine.machine_id,
                kind=VisitKind.SCHEDULED,
                due_date=due_date,
                status=VisitStatus.OPEN,
                closable=True,
                priority_boost=priority_boost,
                incident_source=None,
                close_type=None,
                completed_at=None,
                completed_by_technician_id=None,
                maintenance_event_id=None,
                created_at=created_at,
                updated_at=now,
                sources=merged_sources,
                loading_order_id=merged_loading_order_id,
            )
        else:
            slot = replace(
                existing,
                closable=True,
                priority_boost=priority_boost,
                sources=merged_sources,
                loading_order_id=merged_loading_order_id,
                updated_at=now,
            )
        self._store.upsert(slot)
        return MaterializeResult(
            upserted=1,
            buried=buried,
            extras_absorbed=extras_absorbed,
        )
