from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from beartype import beartype

from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryServiceVisitStore:
    _by_id: dict[str, ServiceVisit] = field(default_factory=dict)

    def get(self, visit_id: str) -> ServiceVisit | None:
        return self._by_id.get(visit_id)

    def upsert(self, visit: ServiceVisit) -> None:
        self._by_id[visit.visit_id] = visit

    def delete(self, visit_id: str) -> None:
        self._by_id.pop(visit_id, None)

    def list_for_machine(
        self,
        machine_id: MachineId,
        *,
        status: VisitStatus | None = None,
    ) -> list[ServiceVisit]:
        items = [
            visit
            for visit in self._by_id.values()
            if visit.machine_id == machine_id and (status is None or visit.status == status)
        ]
        items.sort(key=lambda visit: (visit.due_date, visit.visit_id))
        return items

    def list_open_extras(
        self,
        *,
        incident_source: IncidentSource | None = None,
    ) -> list[ServiceVisit]:
        items = [
            visit
            for visit in self._by_id.values()
            if visit.kind is VisitKind.EXTRA_INCIDENT
            and visit.status is VisitStatus.OPEN
            and (incident_source is None or visit.incident_source is incident_source)
        ]
        items.sort(key=lambda visit: (visit.due_date, visit.visit_id))
        return items

    def list_for_due_date_range(
        self,
        *,
        start: date,
        end: date,
    ) -> list[ServiceVisit]:
        items = [visit for visit in self._by_id.values() if start <= visit.due_date <= end]
        items.sort(key=lambda visit: (visit.due_date, visit.visit_id))
        return items
