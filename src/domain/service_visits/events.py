from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId


@beartype
def visit_force_notify_event_id(visit_id: str, generation: str) -> str:
    return f"visit_force_notify:{visit_id}:{generation}"


@beartype
@dataclass(frozen=True, slots=True)
class ServiceVisitForceNotifyRequested:
    event_id: EventId
    visit_id: str
    machine_id: MachineId
    technician_id: TechnicianId
    technician_display: str
    telegram_user_id: int | None
    outcome: str
    incident_source: str | None
    machine_display: str | None
    location_display: str | None
    occurred_at: datetime
