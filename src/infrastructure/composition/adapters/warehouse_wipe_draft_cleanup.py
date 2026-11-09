from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.technician_settlement.draft import DraftKind
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.domain.ids import TechnicianId

_DRAFT_KINDS: tuple[DraftKind, ...] = ("inventory", "exit")


@beartype
@dataclass(frozen=True, slots=True)
class SettlementDraftWipeCleanup:
    draft_store: ReconciliationDraftStore

    @beartype
    def has_draft_for_technician(self, technician_id: TechnicianId) -> bool:
        return any(
            self.draft_store.get(technician_id.value, kind) is not None for kind in _DRAFT_KINDS
        )

    @beartype
    def delete_for_technician(self, technician_id: TechnicianId) -> int:
        deleted = 0
        for kind in _DRAFT_KINDS:
            if self.draft_store.get(technician_id.value, kind) is not None:
                self.draft_store.delete(technician_id.value, kind)
                deleted += 1
        return deleted
