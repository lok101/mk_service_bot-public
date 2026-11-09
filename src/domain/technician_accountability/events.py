from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import BatchId, EventId, FindingId, MachineId, TechnicianId


@runtime_checkable
class AccountabilityEvent(Protocol):
    @property
    def event_id(self) -> EventId: ...

    @property
    def occurred_at(self) -> datetime: ...


@beartype
@dataclass(frozen=True, slots=True)
class PhotoDuplicateSuspected:
    event_id: EventId
    finding_id: FindingId
    technician_id: TechnicianId
    new_batch_id: BatchId
    matched_batch_id: BatchId
    new_machine_id: MachineId
    matched_machine_id: MachineId
    content_hash: str
    photo_index: int
    detected_at: datetime
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class PhotoDuplicateReviewCompleted:
    event_id: EventId
    finding_id: FindingId
    technician_id: TechnicianId
    verdict: Literal["confirmed", "false_positive"]
    reviewed_at: datetime
    occurred_at: datetime
    reviewer_note: str = ""
