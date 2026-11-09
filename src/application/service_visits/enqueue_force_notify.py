from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.service_visits.force_notify_ports import (
    AssignedTechnicianResolver,
    VisitForceNotifyEventPublisher,
)
from src.application.service_visits.models import IncidentSource
from src.application.service_visits.open_incident_result import (
    OpenIncidentResult,
    VisitForceOutcome,
)
from src.domain.ids import EventId
from src.domain.service_visits import (
    ServiceVisitForceNotifyRequested,
    visit_force_notify_event_id,
)

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class EnqueueVisitForceNotify:
    publisher: VisitForceNotifyEventPublisher
    resolver: AssignedTechnicianResolver
    enabled: bool

    def execute(
        self,
        *,
        result: OpenIncidentResult,
        incident_source: IncidentSource | None,
        machine_display: str | None = None,
        location_display: str | None = None,
        occurred_at: datetime,
    ) -> bool:
        if result.outcome is VisitForceOutcome.NOOP:
            return False
        if not self.enabled:
            return False
        if result.visit_id is None or result.generation is None:
            return False
        ref = self.resolver.resolve(result.machine_id)
        if ref is None:
            _LOGGER.info(
                "visit_force_notify_skipped_unassigned",
                extra={
                    "machine_id": result.machine_id.value,
                    "visit_id": result.visit_id,
                },
            )
            return False
        event = ServiceVisitForceNotifyRequested(
            event_id=EventId(visit_force_notify_event_id(result.visit_id, result.generation)),
            visit_id=result.visit_id,
            machine_id=result.machine_id,
            technician_id=ref.technician_id,
            technician_display=ref.display_name,
            telegram_user_id=ref.telegram_user_id,
            outcome=result.outcome.value,
            incident_source=incident_source.value if incident_source is not None else None,
            machine_display=machine_display,
            location_display=location_display,
            occurred_at=occurred_at,
        )
        self.publisher.publish(event)
        _LOGGER.info(
            "visit_force_notify_enqueued",
            extra={
                "visit_id": result.visit_id,
                "machine_id": result.machine_id.value,
                "technician_id": ref.technician_id.value,
                "outcome": result.outcome.value,
            },
        )
        return True
