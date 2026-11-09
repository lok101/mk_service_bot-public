from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId


@beartype
def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@beartype
def should_upsert_last_maintenance(
    incoming: TechnicianLastMaintenanceSnapshot,
    existing: TechnicianLastMaintenanceSnapshot | None,
) -> bool:
    if existing is None:
        return True
    return _ensure_aware(incoming.completed_at) >= _ensure_aware(existing.completed_at)


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianLastMaintenanceSnapshot:
    technician_id: TechnicianId
    machine_id: MachineId
    completed_at: datetime
