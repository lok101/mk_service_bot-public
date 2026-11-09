from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class AlwaysDenyAdditionalMaintenance:
    @beartype
    def allows(self, machine_id: MachineId, at: datetime) -> bool:
        return False
