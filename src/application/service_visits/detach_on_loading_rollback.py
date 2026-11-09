from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from beartype import beartype

from src.application.service_visits.models import VisitStatus, VisitTaskSource
from src.application.service_visits.ports import ServiceVisitStore
from src.domain.ids import MachineId

_logger = logging.getLogger(__name__)


@beartype
class DetachVisitTaskOnLoadingRollback:
    """Conditionally detach micromarket_loading provenance after order rollback."""

    def __init__(self, *, store: ServiceVisitStore) -> None:
        self._store = store

    @beartype
    def execute(
        self,
        *,
        machine_id: MachineId,
        visit_id: str | None,
        now: datetime,
    ) -> None:
        if visit_id is None:
            _logger.info(
                "detach_visit_on_loading_rollback",
                extra={
                    "machine_id": machine_id.value,
                    "visit_id": None,
                    "detach_action": "noop",
                },
            )
            return

        visit = self._store.get(visit_id)
        if visit is None or visit.status is not VisitStatus.OPEN:
            _logger.info(
                "detach_visit_on_loading_rollback",
                extra={
                    "machine_id": machine_id.value,
                    "visit_id": visit_id,
                    "detach_action": "noop",
                },
            )
            return

        remaining = visit.sources - {VisitTaskSource.MICROMARKET_LOADING}
        if not remaining:
            updated = replace(
                visit,
                status=VisitStatus.CLEARED,
                closable=False,
                sources=frozenset(),
                loading_order_id=None,
                updated_at=now,
            )
            self._store.upsert(updated)
            _logger.info(
                "detach_visit_on_loading_rollback",
                extra={
                    "machine_id": machine_id.value,
                    "visit_id": visit_id,
                    "detach_action": "cleared",
                },
            )
            return

        if (
            remaining == visit.sources
            and visit.loading_order_id is None
            and VisitTaskSource.MICROMARKET_LOADING not in visit.sources
        ):
            _logger.info(
                "detach_visit_on_loading_rollback",
                extra={
                    "machine_id": machine_id.value,
                    "visit_id": visit_id,
                    "detach_action": "noop",
                },
            )
            return

        updated = replace(
            visit,
            sources=remaining,
            loading_order_id=None,
            updated_at=now,
        )
        self._store.upsert(updated)
        _logger.info(
            "detach_visit_on_loading_rollback",
            extra={
                "machine_id": machine_id.value,
                "visit_id": visit_id,
                "detach_action": "sources_updated",
            },
        )
