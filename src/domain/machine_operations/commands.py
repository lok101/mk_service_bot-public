from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import BatchId, TechnicianId
from src.domain.models import RevisionSource
from src.domain.photo_batch import PhotoRef


@beartype
@dataclass(frozen=True, slots=True)
class CompleteRevision:
    technician_id: TechnicianId
    completed_at: datetime
    source: RevisionSource
    form_id: str
    form_token: str


@beartype
@dataclass(frozen=True, slots=True)
class SubmitLoading:
    technician_id: TechnicianId
    submitted_at: datetime
    form_id: str
    form_token: str


@beartype
@dataclass(frozen=True, slots=True)
class CompleteMaintenance:
    technician_id: TechnicianId
    completed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SubmitLoadingPhotos:
    technician_id: TechnicianId
    batch_id: BatchId
    submitted_at: datetime
    photos: tuple[PhotoRef, ...]
    min_photo_count: int

    def __post_init__(self) -> None:
        if self.min_photo_count < 1:
            raise ValueError("min_photo_count must be at least 1")
        if not self.photos:
            raise ValueError("photos must not be empty")
