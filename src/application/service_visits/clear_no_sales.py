from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from beartype import beartype

from src.application.service_visits.models import IncidentSource, VisitKind, VisitStatus
from src.application.service_visits.ports import ServiceVisitStore
from src.application.service_visits.visit_ids import (
    is_day_based_no_sales_visit_id,
    no_sales_incident_visit_id,
)
from src.domain.ids import MachineId


@beartype
class ClearNoSalesIncident:
    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    def execute(self, *, machine_id: MachineId, now: datetime) -> None:
        sticky = self._store.get(no_sales_incident_visit_id(machine_id))
        if sticky is not None and sticky.status is VisitStatus.OPEN:
            self._store.upsert(
                replace(
                    sticky,
                    status=VisitStatus.CLEARED,
                    closable=False,
                    updated_at=now,
                ),
            )
        for visit in self._store.list_for_machine(machine_id, status=VisitStatus.OPEN):
            if (
                visit.kind is VisitKind.EXTRA_INCIDENT
                and visit.incident_source is IncidentSource.NO_SALES
                and is_day_based_no_sales_visit_id(visit.visit_id)
            ):
                self._store.upsert(
                    replace(
                        visit,
                        status=VisitStatus.CLEARED,
                        closable=False,
                        updated_at=now,
                    ),
                )
            if visit.kind is VisitKind.SCHEDULED and visit.priority_boost:
                self._store.upsert(replace(visit, priority_boost=False, updated_at=now))
