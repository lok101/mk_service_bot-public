from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.technician_settlement.draft import DraftKind, ReconciliationDraft


@runtime_checkable
class ReconciliationDraftStore(Protocol):
    @beartype
    def upsert(self, draft: ReconciliationDraft) -> None: ...

    @beartype
    def get(self, technician_id: str, kind: DraftKind) -> ReconciliationDraft | None: ...

    @beartype
    def delete(self, technician_id: str, kind: DraftKind) -> None: ...

    @beartype
    def list_by_kind(self, kind: DraftKind) -> tuple[ReconciliationDraft, ...]: ...

    @beartype
    def count_all(self) -> int: ...

    @beartype
    def delete_all(self) -> None: ...
