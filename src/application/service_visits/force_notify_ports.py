from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class AssignedTechnicianRef:
    technician_id: TechnicianId
    display_name: str
    telegram_user_id: int | None


@runtime_checkable
class AssignedTechnicianResolver(Protocol):
    @beartype
    def resolve(self, machine_id: MachineId) -> AssignedTechnicianRef | None: ...


@runtime_checkable
class VisitForceNotifyEventPublisher(Protocol):
    """Narrow publish port; satisfied by OutboxDomainEventPublisher."""

    @beartype
    def publish(self, event: DomainEvent) -> None: ...
