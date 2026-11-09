from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from beartype import beartype

from src.application.reference_data.location_roster import (
    LocationRosterAuditRecord,
    LocationRosterEntry,
)
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryLocationRosterStore:
    _by_id: dict[MachineId, LocationRosterEntry] = field(default_factory=dict)
    _audit: list[LocationRosterAuditRecord] = field(default_factory=list)

    def get(self, machine_id: MachineId) -> LocationRosterEntry | None:
        return self._by_id.get(machine_id)

    def list_all(self) -> tuple[LocationRosterEntry, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id

    def replace_all(self, entries: tuple[LocationRosterEntry, ...]) -> None:
        self._by_id = {entry.machine_id: entry for entry in entries}

    def save_batch(
        self,
        entries: tuple[LocationRosterEntry, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
    ) -> None:
        for entry in entries:
            before = self._by_id.get(entry.machine_id)
            self._by_id[entry.machine_id] = entry
            self._audit.append(
                LocationRosterAuditRecord(
                    at=at,
                    actor_telegram_user_id=actor_telegram_user_id,
                    machine_id=entry.machine_id,
                    before=before,
                    after=entry,
                ),
            )

    def list_audit(self) -> tuple[LocationRosterAuditRecord, ...]:
        return tuple(self._audit)
