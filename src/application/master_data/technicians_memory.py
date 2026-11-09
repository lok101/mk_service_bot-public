from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.master_data.technicians import Technician
from src.domain.ids import TechnicianId


@beartype
@dataclass(slots=True)
class InMemoryTechnicianStore:
    _by_id: dict[TechnicianId, Technician] = field(default_factory=dict)

    def get(self, technician_id: TechnicianId) -> Technician | None:
        return self._by_id.get(technician_id)

    def upsert(self, technician: Technician) -> None:
        self._by_id[technician.technician_id] = technician

    def list_all(self) -> tuple[Technician, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id
