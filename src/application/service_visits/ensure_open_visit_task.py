from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime

from beartype import beartype

from src.application.service_visits.models import (
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
@dataclass(frozen=True, slots=True)
class EnsureOpenVisitTaskResult:
    visit_id: str
    created: bool


@beartype
class EnsureOpenVisitTask:
    """Find or create at most one open working VisitTask for (machine, ops_day)."""

    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    @beartype
    def execute(
        self,
        *,
        machine_id: MachineId,
        ops_day: date,
        source: VisitTaskSource,
        now: datetime,
        loading_order_id: str | None = None,
    ) -> EnsureOpenVisitTaskResult:
        existing = self._find_open_working(machine_id=machine_id, ops_day=ops_day)
        if existing is not None:
            existing = self._coalesce_to_scheduled(
                existing,
                machine_id=machine_id,
                ops_day=ops_day,
                now=now,
            )
            updated = self._attach(
                existing,
                source=source,
                loading_order_id=loading_order_id,
                now=now,
            )
            if updated is not existing:
                self._store.upsert(updated)
            _logger.info(
                "ensure_open_visit_task",
                extra={
                    "machine_id": machine_id.value,
                    "visit_id": updated.visit_id,
                    "source": source.value,
                    "order_id": loading_order_id,
                    "created": False,
                },
            )
            return EnsureOpenVisitTaskResult(visit_id=updated.visit_id, created=False)

        visit_id = scheduled_visit_id(machine_id, ops_day)
        visit = ServiceVisit(
            visit_id=visit_id,
            machine_id=machine_id,
            kind=VisitKind.SCHEDULED,
            due_date=ops_day,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=now,
            updated_at=now,
            sources=frozenset({source}),
            loading_order_id=loading_order_id,
        )
        self._store.upsert(visit)
        _logger.info(
            "ensure_open_visit_task",
            extra={
                "machine_id": machine_id.value,
                "visit_id": visit_id,
                "source": source.value,
                "order_id": loading_order_id,
                "created": True,
            },
        )
        return EnsureOpenVisitTaskResult(visit_id=visit_id, created=True)

    def _find_open_working(
        self,
        *,
        machine_id: MachineId,
        ops_day: date,
    ) -> ServiceVisit | None:
        open_visits = self._store.list_for_machine(machine_id, status=VisitStatus.OPEN)
        same_day = [visit for visit in open_visits if visit.due_date == ops_day]
        # Prefer roster/canonical scheduled id so materialize does not fork a second OPEN.
        canonical_id = scheduled_visit_id(machine_id, ops_day)
        canonical = next((visit for visit in same_day if visit.visit_id == canonical_id), None)
        if canonical is not None:
            return canonical
        scheduled = next((visit for visit in same_day if visit.kind is VisitKind.SCHEDULED), None)
        if scheduled is not None:
            return scheduled
        # Do not reuse EXTRA: materialize clears extras and would leave order.visit_id stale.
        return None

    def _coalesce_to_scheduled(
        self,
        visit: ServiceVisit,
        *,
        machine_id: MachineId,
        ops_day: date,
        now: datetime,
    ) -> ServiceVisit:
        canonical_id = scheduled_visit_id(machine_id, ops_day)
        if visit.visit_id == canonical_id:
            return visit
        promoted = replace(
            visit,
            visit_id=canonical_id,
            kind=VisitKind.SCHEDULED,
            updated_at=now,
        )
        self._store.upsert(promoted)
        self._store.upsert(
            replace(
                visit,
                status=VisitStatus.CLEARED,
                closable=False,
                updated_at=now,
            )
        )
        return promoted

    def _attach(
        self,
        visit: ServiceVisit,
        *,
        source: VisitTaskSource,
        loading_order_id: str | None,
        now: datetime,
    ) -> ServiceVisit:
        new_sources = visit.sources | {source}
        new_order_id = visit.loading_order_id
        if loading_order_id is not None and visit.loading_order_id is None:
            new_order_id = loading_order_id
        if new_sources == visit.sources and new_order_id == visit.loading_order_id:
            return visit
        return replace(
            visit,
            sources=new_sources,
            loading_order_id=new_order_id,
            updated_at=now,
        )
