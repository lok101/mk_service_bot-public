from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from beartype import beartype

from src.application.technician_accountability.ports import TechnicianAccountabilityRepository
from src.domain.ids import TechnicianId
from src.domain.technician_accountability import TechnicianAccountability
from src.domain.technician_accountability.events import AccountabilityEvent

T = TypeVar("T")


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianAccountabilityExecutor:
    repository: TechnicianAccountabilityRepository

    @beartype
    def execute(
        self,
        technician_id: TechnicianId,
        command_fn: Callable[[TechnicianAccountability], T],
    ) -> T:
        aggregate = self.repository.get(technician_id)
        result = command_fn(aggregate)
        pending_events = aggregate.collect_events()
        if pending_events:
            self.repository.save(aggregate)
            aggregate.clear_pending_events()
        elif isinstance(result, AccountabilityEvent):
            return result
        return result
