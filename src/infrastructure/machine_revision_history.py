from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.ports import MachineRevisionHistoryReader
from src.application.machine_operations.ports import EventStore
from src.domain.ids import MachineId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    RevisionCompleted,
)


@beartype
@dataclass(frozen=True, slots=True)
class EventStoreMachineRevisionHistoryReader(MachineRevisionHistoryReader):
    event_store: EventStore

    @beartype
    def list_revisions(self, machine_id: MachineId) -> tuple[RevisionCompleted, ...]:
        events = self.event_store.get_events_for_machine(machine_id)
        revisions = [event for event in events if isinstance(event, RevisionCompleted)]
        return tuple(sorted(revisions, key=lambda revision: revision.completed_at))

    @beartype
    def list_loadings(self, machine_id: MachineId) -> tuple[LoadingSubmitted, ...]:
        events = self.event_store.get_events_for_machine(machine_id)
        loadings = [event for event in events if isinstance(event, LoadingSubmitted)]
        return tuple(sorted(loadings, key=lambda loading: loading.occurred_at))
