from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.technician_accountability.ports import (
    TechnicianAccountabilityEventStore,
    TechnicianAccountabilityRepository,
)
from src.domain.ids import TechnicianId
from src.domain.technician_accountability import TechnicianAccountability
from src.domain.technician_accountability.events import AccountabilityEvent


@beartype
@dataclass
class InMemoryTechnicianAccountabilityEventStore(TechnicianAccountabilityEventStore):
    _events: list[AccountabilityEvent] = field(default_factory=list)

    @beartype
    def append(self, event: AccountabilityEvent) -> None:
        if any(existing.event_id == event.event_id for existing in self._events):
            return
        self._events.append(event)

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[AccountabilityEvent]:
        return [
            event
            for event in self._events
            if getattr(event, "technician_id", None) == technician_id
        ]


@beartype
@dataclass(frozen=True, slots=True)
class InMemoryTechnicianAccountabilityRepository(TechnicianAccountabilityRepository):
    event_store: TechnicianAccountabilityEventStore

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianAccountability:
        events = self.event_store.get_events_for_technician(technician_id)
        return TechnicianAccountability.rehydrate(technician_id, events)

    @beartype
    def save(self, aggregate: TechnicianAccountability) -> None:
        for event in aggregate.collect_events():
            self.event_store.append(event)
