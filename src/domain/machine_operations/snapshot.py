from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import RevisionId, TechnicianId
from src.domain.models import RevisionSource


@beartype
@dataclass(frozen=True, slots=True)
class RevisionSnapshot:
    revision_id: RevisionId
    technician_id: TechnicianId
    completed_at: datetime
    source: RevisionSource
    form_id: str
    form_token: str
    responsibility_expires_at: datetime | None = None
