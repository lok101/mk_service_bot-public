from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime

from beartype import beartype

from src.application.service_visits.models import (
    CloseType,
    ServiceVisit,
    VisitKind,
    VisitStatus,
    VisitTaskSource,
)
from src.application.service_visits.ports import ServiceVisitStore
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId

_logger = logging.getLogger(__name__)


@beartype
class CompleteOpenVisitTask:
    """Complete at most one open working VisitTask for (machine, ops_day)."""

    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    @beartype
    def execute(
        self,
        *,
        machine_id: MachineId,
        ops_day: date,
        now: datetime,
        source: VisitTaskSource,
    ) -> str | None:
        visit = self._find_open_working(machine_id=machine_id, ops_day=ops_day)
        if visit is None:
            return None
        if visit.kind is VisitKind.SCHEDULED:
            close_type = CloseType.SCHEDULED
        elif visit.kind is VisitKind.EXTRA_INCIDENT:
            close_type = CloseType.EXTRA_INCIDENT
        else:
            close_type = CloseType.SPONTANEOUS
        sources = visit.sources | {source}
        self._store.upsert(
            replace(
                visit,
                status=VisitStatus.COMPLETED,
                closable=False,
                priority_boost=False,
                close_type=close_type,
                completed_at=now,
                updated_at=now,
                sources=sources,
            )
        )
        _logger.info(
            "complete_open_visit_task",
            extra={
                "machine_id": machine_id.value,
                "visit_id": visit.visit_id,
                "source": source.value,
            },
        )
        return visit.visit_id

    def _find_open_working(
        self,
        *,
        machine_id: MachineId,
        ops_day: date,
    ) -> ServiceVisit | None:
        open_visits = self._store.list_for_machine(machine_id, status=VisitStatus.OPEN)
        same_day = [visit for visit in open_visits if visit.due_date == ops_day]
        canonical_id = scheduled_visit_id(machine_id, ops_day)
        canonical = next((visit for visit in same_day if visit.visit_id == canonical_id), None)
        if canonical is not None:
            return canonical
        scheduled = next((visit for visit in same_day if visit.kind is VisitKind.SCHEDULED), None)
        if scheduled is not None:
            return scheduled
        return same_day[0] if same_day else None
