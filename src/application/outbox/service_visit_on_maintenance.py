from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.service_visits import CloseServiceVisit
from src.application.service_visits.ports import MachineWeekdaysLookup
from src.domain.events import DomainEvent
from src.domain.machine_operations import (
    MaintenanceCompleted,
    PhotosSubmitted,
    maintenance_completed_at_from_event,
)


@beartype
@dataclass(frozen=True, slots=True)
class ServiceVisitOnMaintenanceHandler:
    closer: CloseServiceVisit
    weekdays: MachineWeekdaysLookup
    timezone: ZoneInfo
    day_end_hour: int

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, (MaintenanceCompleted, PhotosSubmitted)):
            raise NonRetryableOutboxError(
                f"Unsupported event: {type(event).__name__}",
            )
        completed_at = maintenance_completed_at_from_event(event)
        if completed_at is None:
            return
        self.closer.execute(
            machine_id=event.machine_id,
            technician_id=event.technician_id,
            maintenance_event_id=event.event_id,
            completed_at=completed_at,
            service_weekdays=self.weekdays.weekdays_for(event.machine_id),
            timezone=self.timezone,
            day_end_hour=self.day_end_hour,
            now=event.occurred_at,
        )
