from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from beartype import beartype

from src.application.service_visits.models import VisitKind, VisitStatus
from src.application.service_visits.ports import ServiceVisitStore
from src.application.service_visits.visit_ids import offline_incident_visit_id
from src.domain.ids import EventId, MachineId


@beartype
class ClearOfflineIncident:
    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    def execute(
        self,
        *,
        opened_event_id: EventId,
        machine_id: MachineId,
        now: datetime,
    ) -> None:
        extra = self._store.get(offline_incident_visit_id(opened_event_id))
        if extra is not None and extra.status is VisitStatus.OPEN:
            self._store.upsert(
                replace(
                    extra,
                    status=VisitStatus.CLEARED,
                    closable=False,
                    updated_at=now,
                ),
            )
        for visit in self._store.list_for_machine(machine_id, status=VisitStatus.OPEN):
            if visit.kind is VisitKind.SCHEDULED and visit.priority_boost:
                self._store.upsert(replace(visit, priority_boost=False, updated_at=now))
