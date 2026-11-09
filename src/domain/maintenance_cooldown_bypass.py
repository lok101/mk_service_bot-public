from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceCooldownBypassSnapshot:
    service_date: date
    activated_at: datetime
    reason: str | None = None
