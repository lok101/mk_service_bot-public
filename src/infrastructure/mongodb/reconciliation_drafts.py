from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.technician_settlement.draft import (
    DraftKind,
    ReconciliationDraft,
    draft_from_document,
    draft_to_document,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class ReconciliationDraftsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def delete_many(self, filter: dict[str, Any]) -> Any: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoReconciliationDraftStore(ReconciliationDraftStore):
    _collection: ReconciliationDraftsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: ReconciliationDraftsCollection,
    ) -> MongoReconciliationDraftStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoReconciliationDraftStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.reconciliation_drafts_collection,
            owner="MongoReconciliationDraftStore",
            client=client,
        )
        return cls(_collection=collection)

    @beartype
    def upsert(self, draft: ReconciliationDraft) -> None:
        document = draft_to_document(draft)
        self._collection.replace_one({"_id": draft.document_id}, document, upsert=True)

    @beartype
    def get(self, technician_id: str, kind: DraftKind) -> ReconciliationDraft | None:
        document = self._collection.find_one({"_id": f"{technician_id}:{kind}"})
        if document is None:
            return None
        return draft_from_document(document)

    @beartype
    def delete(self, technician_id: str, kind: DraftKind) -> None:
        self._collection.delete_one({"_id": f"{technician_id}:{kind}"})

    @beartype
    def list_by_kind(self, kind: DraftKind) -> tuple[ReconciliationDraft, ...]:
        documents = list(self._collection.find({"kind": kind}))
        drafts = [draft_from_document(document) for document in documents]
        return tuple(sorted(drafts, key=lambda draft: draft.technician_id))

    @beartype
    def count_all(self) -> int:
        return int(self._collection.count_documents({}))

    @beartype
    def delete_all(self) -> None:
        self._collection.delete_many({})
