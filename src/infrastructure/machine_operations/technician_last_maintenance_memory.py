from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.domain.ids import TechnicianId
from src.domain.technician_last_maintenance import (
    TechnicianLastMaintenanceSnapshot,
    should_upsert_last_maintenance,
)


@beartype
@dataclass(slots=True)
class InMemoryTechnicianLastMaintenanceProjection:
    _by_technician: dict[str, TechnicianLastMaintenanceSnapshot] = field(default_factory=dict)

    @beartype
    def get_last(self, technician_id: TechnicianId) -> TechnicianLastMaintenanceSnapshot | None:
        return self._by_technician.get(technician_id.value)

    @beartype
    def upsert(self, snapshot: TechnicianLastMaintenanceSnapshot) -> None:
        existing = self.get_last(snapshot.technician_id)
        if not should_upsert_last_maintenance(snapshot, existing):
            return
        self._by_technician[snapshot.technician_id.value] = snapshot
