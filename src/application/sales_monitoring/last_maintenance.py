from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.machine_operations.ports import EventStore
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations.events import (
    MaintenanceCompleted,
    PhotosSubmitted,
    maintenance_completed_at_from_event,
)


@beartype
@dataclass(frozen=True, slots=True)
class LastMaintenanceSnapshot:
    technician_id: TechnicianId
    completed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class EventStoreLastMaintenanceByMachine:
    event_store: EventStore

    @beartype
    def get(self, machine_id: MachineId) -> LastMaintenanceSnapshot | None:
        latest_technician_id: TechnicianId | None = None
        latest_completed_at: datetime | None = None
        for event in self.event_store.get_events_for_machine(machine_id):
            if not isinstance(event, (MaintenanceCompleted, PhotosSubmitted)):
                continue
            completed_at = maintenance_completed_at_from_event(event)
            if completed_at is None:
                continue
            if latest_completed_at is None or completed_at > latest_completed_at:
                latest_technician_id = event.technician_id
                latest_completed_at = completed_at
        if latest_technician_id is None or latest_completed_at is None:
            return None
        return LastMaintenanceSnapshot(
            technician_id=latest_technician_id,
            completed_at=latest_completed_at,
        )
