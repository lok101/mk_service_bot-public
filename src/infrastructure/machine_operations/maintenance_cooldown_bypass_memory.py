from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot


@beartype
@dataclass(frozen=True, slots=True)
class NullMaintenanceCooldownBypassReader:
    @beartype
    def get_active(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> MaintenanceCooldownBypassSnapshot | None:
        _ = checked_at
        return None
