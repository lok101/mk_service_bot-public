from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from beartype import beartype

from src.application.reference_data.location_roster import (
    LocationRosterConflict,
    LocationRosterEntry,
)
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryLocationRosterDraftStore:
    _by_id: dict[MachineId, LocationRosterEntry] = field(default_factory=dict)

    def get(self, machine_id: MachineId) -> LocationRosterEntry | None:
        return self._by_id.get(machine_id)

    def list_all(self) -> tuple[LocationRosterEntry, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id

    def replace_all(self, entries: tuple[LocationRosterEntry, ...]) -> None:
        self._by_id = {entry.machine_id: entry for entry in entries}

    def upsert(
        self,
        entry: LocationRosterEntry,
        *,
        expected_updated_at: datetime | None,
    ) -> LocationRosterEntry:
        current = self._by_id.get(entry.machine_id)
        if expected_updated_at is None:
            if current is not None:
                raise LocationRosterConflict()
        elif current is None or current.updated_at != expected_updated_at:
            raise LocationRosterConflict()
        self._by_id[entry.machine_id] = entry
        return entry
