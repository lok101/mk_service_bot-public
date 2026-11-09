from __future__ import annotations

from datetime import datetime

from beartype import beartype

from src.application.machine_operations.ports import EventStore
from src.domain.ids import MachineId
from src.domain.machine_operations.events import (
    MaintenanceCompleted,
    PhotosSubmitted,
    maintenance_completed_at_from_event,
)


@beartype
class EventStoreServiceFactCounter:
    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def count_completed(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> int:
        events = self._event_store.get_events_for_machine(machine_id)
        total = 0
        for event in events:
            if not isinstance(event, (MaintenanceCompleted, PhotosSubmitted)):
                continue
            completed_at = maintenance_completed_at_from_event(event)
            if completed_at is None:
                continue
            if opened_at < completed_at <= closed_at:
                total += 1
        return total
