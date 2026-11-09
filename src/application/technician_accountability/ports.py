from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import TechnicianId
from src.domain.technician_accountability import TechnicianAccountability
from src.domain.technician_accountability.events import AccountabilityEvent


@runtime_checkable
class TechnicianAccountabilityEventStore(Protocol):
    @beartype
    def append(self, event: AccountabilityEvent) -> None: ...

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[AccountabilityEvent]: ...


@runtime_checkable
class TechnicianAccountabilityRepository(Protocol):
    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianAccountability: ...

    @beartype
    def save(self, aggregate: TechnicianAccountability) -> None: ...
