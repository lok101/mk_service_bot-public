from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from beartype import beartype

from src.domain.ids import MachineId


class VisitForceOutcome(StrEnum):
    CREATED_EXTRA = "created_extra"
    REOPENED_EXTRA = "reopened_extra"
    BOOSTED_SCHEDULED = "boosted_scheduled"
    NOOP = "noop"


@beartype
@dataclass(frozen=True, slots=True)
class OpenIncidentResult:
    outcome: VisitForceOutcome
    machine_id: MachineId
    visit_id: str | None
    generation: str | None
