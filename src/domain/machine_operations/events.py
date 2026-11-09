from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.models import RevisionSource


@runtime_checkable
class DomainEvent(Protocol):
    @property
    def event_id(self) -> EventId: ...

    @property
    def occurred_at(self) -> datetime: ...


@runtime_checkable
class InventoryFormMoveSubmitted(Protocol):
    """Loading form submissions share the MoySklad move shape."""

    @property
    def event_id(self) -> EventId: ...

    @property
    def technician_id(self) -> TechnicianId: ...

    @property
    def machine_id(self) -> MachineId: ...

    @property
    def submitted_at(self) -> datetime: ...


@beartype
@dataclass(frozen=True, slots=True)
class RevisionCompleted:
    event_id: EventId
    revision_id: RevisionId
    technician_id: TechnicianId
    machine_id: MachineId
    completed_at: datetime
    occurred_at: datetime
    source: RevisionSource
    form_id: str
    form_token: str
    responsibility_expires_at: datetime | None = None


@beartype
@dataclass(frozen=True, slots=True)
class LoadingSubmitted:
    event_id: EventId
    technician_id: TechnicianId
    machine_id: MachineId
    submitted_at: datetime
    occurred_at: datetime
    form_id: str
    form_token: str


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceCompleted:
    event_id: EventId
    technician_id: TechnicianId
    machine_id: MachineId
    completed_at: datetime
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class PhotosSubmitted:
    event_id: EventId
    batch_id: BatchId
    technician_id: TechnicianId
    machine_id: MachineId
    photo_count: int
    submitted_at: datetime
    occurred_at: datetime
    purpose: Literal["loading"] = "loading"
    maintenance_completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.photo_count < 1:
            raise ValueError("photo_count must be positive")


@beartype
def maintenance_completed_at_from_event(
    event: MaintenanceCompleted | PhotosSubmitted,
) -> datetime | None:
    if isinstance(event, MaintenanceCompleted):
        return event.completed_at
    return event.maintenance_completed_at
