from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)
from src.config.mongodb import MongoSettings
from src.domain.technician_settlement.residual_document import ReconciliationResidualDocument
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class ResidualDocumentsCollection(Protocol):
    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def delete_many(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _to_document(document: ReconciliationResidualDocument) -> dict[str, Any]:
    return {
        "residual_document_id": document.residual_document_id.value,
        "session_id": document.session_id.value,
        "technician_id": document.technician_id.value,
        "kind": document.kind,
        "residual_by_sku": {
            sku: format(value, "f") for sku, value in document.residual_by_sku.items()
        },
        "created_at": document.created_at.astimezone(UTC),
    }


@beartype
@dataclass(frozen=True, slots=True)
class MongoReconciliationResidualDocumentRepository(ReconciliationResidualDocumentRepository):
    _collection: ResidualDocumentsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: ResidualDocumentsCollection,
    ) -> MongoReconciliationResidualDocumentRepository:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoReconciliationResidualDocumentRepository:
        collection = resolve_collection(
            settings,
            collection_name=settings.reconciliation_residual_documents_collection,
            owner="MongoReconciliationResidualDocumentRepository",
            client=client,
        )
        return cls(_collection=collection)

    @beartype
    def save(self, document: ReconciliationResidualDocument) -> None:
        self._collection.update_one(
            {"residual_document_id": document.residual_document_id.value},
            {"$set": _to_document(document)},
            upsert=True,
        )

    @beartype
    def count_all(self) -> int:
        return int(self._collection.count_documents({}))

    @beartype
    def delete_all(self) -> int:
        result = self._collection.delete_many({})
        return int(getattr(result, "deleted_count", 0))
