from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from beartype import beartype

from src.application.service_visits.models import IncidentSource, VisitStatus
from src.application.service_visits.ports import ServiceVisitStore
from src.application.service_visits.visit_ids import is_day_based_no_sales_visit_id


@beartype
class MigrateDayBasedNoSalesVisits:
    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    def execute(self, *, now: datetime) -> int:
        cleared = 0
        for visit in self._store.list_open_extras(incident_source=IncidentSource.NO_SALES):
            if visit.status is VisitStatus.OPEN and is_day_based_no_sales_visit_id(visit.visit_id):
                self._store.upsert(
                    replace(
                        visit,
                        status=VisitStatus.CLEARED,
                        closable=False,
                        updated_at=now,
                    ),
                )
                cleared += 1
        return cleared
