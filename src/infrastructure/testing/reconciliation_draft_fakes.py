from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.technician_settlement.draft import (
    DraftKind,
    ReconciliationDraft,
    draft_from_document,
    draft_to_document,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore


@beartype
@dataclass(slots=True)
class InMemoryReconciliationDraftStore(ReconciliationDraftStore):
    _by_id: dict[str, ReconciliationDraft] = field(default_factory=dict)

    @beartype
    def upsert(self, draft: ReconciliationDraft) -> None:
        # Same encode/decode path as Mongo — keeps Decimal money maps consistent in tests.
        self._by_id[draft.document_id] = draft_from_document(draft_to_document(draft))

    @beartype
    def get(self, technician_id: str, kind: DraftKind) -> ReconciliationDraft | None:
        return self._by_id.get(f"{technician_id}:{kind}")

    @beartype
    def delete(self, technician_id: str, kind: DraftKind) -> None:
        self._by_id.pop(f"{technician_id}:{kind}", None)

    @beartype
    def list_by_kind(self, kind: DraftKind) -> tuple[ReconciliationDraft, ...]:
        drafts = [draft for draft in self._by_id.values() if draft.kind == kind]
        return tuple(sorted(drafts, key=lambda draft: draft.technician_id))

    @beartype
    def count_all(self) -> int:
        return len(self._by_id)

    @beartype
    def delete_all(self) -> None:
        self._by_id.clear()
