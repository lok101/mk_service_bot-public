from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId


class VisitKind(StrEnum):
    SCHEDULED = "scheduled"
    EXTRA_INCIDENT = "extra_incident"


class VisitStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    MISSED = "missed"
    CLEARED = "cleared"


class CloseType(StrEnum):
    SCHEDULED = "scheduled"
    EXTRA_INCIDENT = "extra_incident"
    SPONTANEOUS = "spontaneous"
    UNSCHEDULED_ROSTER = "unscheduled_roster"


class IncidentSource(StrEnum):
    OFFLINE = "offline"
    NO_SALES = "no_sales"


class VisitTaskSource(StrEnum):
    """Provenance for VisitTask (= ServiceVisit) open/ensure sources."""

    ROSTER = "roster"
    MONITORING = "monitoring"
    MICROMARKET_LOADING = "micromarket_loading"
    FIELD_ACTIVITY = "field_activity"


@beartype
@dataclass(frozen=True, slots=True)
class ServiceVisit:
    visit_id: str
    machine_id: MachineId
    kind: VisitKind
    due_date: date
    status: VisitStatus
    closable: bool
    priority_boost: bool
    incident_source: IncidentSource | None
    close_type: CloseType | None
    completed_at: datetime | None
    completed_by_technician_id: TechnicianId | None
    maintenance_event_id: EventId | None
    created_at: datetime
    updated_at: datetime
    sources: frozenset[VisitTaskSource] = frozenset()
    loading_order_id: str | None = None
