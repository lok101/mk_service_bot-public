from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from beartype import beartype

from src.domain.ids import BatchId, FindingId, TechnicianId

PhotoIntegrityStatus = Literal["pending_review", "confirmed", "false_positive"]


@beartype
@dataclass(frozen=True, slots=True)
class PhotoIntegrityFinding:
    finding_id: FindingId
    status: PhotoIntegrityStatus
    new_batch_id: BatchId
    matched_batch_id: BatchId
    technician_id: TechnicianId
    content_hash: str
    photo_index: int
    detected_at: datetime
    reviewed_at: datetime | None = None
    alert_sent_at: datetime | None = None
