from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.reference_data import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    ReferenceDataSyncError,
)
from src.application.reference_data.ports import ReferenceDataSnapshotStore
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class ReferenceDataCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@beartype
def snapshot_to_document(snapshot: ReferenceDataSnapshot) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": snapshot.source_id.value,
        "rows": [list(row) for row in snapshot.rows],
        "content_hash": snapshot.content_hash,
        "last_fetched_at": snapshot.last_fetched_at,
        "content_updated_at": snapshot.content_updated_at,
        "last_sync_error": None,
    }
    if snapshot.last_sync_error is not None:
        document["last_sync_error"] = {
            "message": snapshot.last_sync_error.message,
            "at": snapshot.last_sync_error.at,
        }
    return document


@beartype
def snapshot_from_document(document: dict[str, Any]) -> ReferenceDataSnapshot:
    return snapshot_from_document_for_source(
        document,
        ReferenceDataSourceId(document["_id"]),
    )


@beartype
def snapshot_from_document_for_source(
    document: dict[str, Any],
    source_id: ReferenceDataSourceId,
) -> ReferenceDataSnapshot:
    raw_rows = document.get("rows", [])
    rows = tuple(tuple(str(cell) for cell in row) for row in raw_rows)
    raw_error = document.get("last_sync_error")
    error: ReferenceDataSyncError | None = None
    if isinstance(raw_error, dict):
        error = ReferenceDataSyncError(
            message=str(raw_error.get("message", "")),
            at=_ensure_aware(raw_error["at"]),
        )
    return ReferenceDataSnapshot(
        source_id=source_id,
        rows=rows,
        content_hash=str(document.get("content_hash", "")),
        last_fetched_at=_ensure_aware(document["last_fetched_at"]),
        content_updated_at=_ensure_aware(document["content_updated_at"]),
        last_sync_error=error,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoReferenceDataSnapshotStore(ReferenceDataSnapshotStore):
    _collection: ReferenceDataCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoReferenceDataSnapshotStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.reference_data_snapshots_collection,
            owner="MongoReferenceDataSnapshotStore",
            client=client,
        )
        return cls(_collection=collection)

    @beartype
    def get(self, source_id: ReferenceDataSourceId) -> ReferenceDataSnapshot | None:
        document = self._collection.find_one({"_id": source_id.value})
        if document is None:
            return None
        return snapshot_from_document(document)

    @beartype
    def get_by_id(self, snapshot_id: str) -> ReferenceDataSnapshot | None:
        document = self._collection.find_one({"_id": snapshot_id})
        if document is None:
            return None
        try:
            source_id = ReferenceDataSourceId(snapshot_id)
        except ValueError:
            # Legacy Mongo `_id` (e.g. technician_locations) — migrate only needs rows/meta.
            source_id = ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS
        return snapshot_from_document_for_source(document, source_id)

    @beartype
    def delete_by_id(self, snapshot_id: str) -> None:
        self._collection.delete_one({"_id": snapshot_id})

    @beartype
    def put(self, snapshot: ReferenceDataSnapshot) -> None:
        self._collection.replace_one(
            {"_id": snapshot.source_id.value},
            snapshot_to_document(snapshot),
            upsert=True,
        )

    @beartype
    def record_sync_error(
        self,
        source_id: ReferenceDataSourceId,
        message: str,
        at: datetime,
    ) -> None:
        self._collection.update_one(
            {"_id": source_id.value},
            {
                "$set": {"last_sync_error": {"message": message, "at": at}},
                "$setOnInsert": {
                    "rows": [],
                    "content_hash": "",
                    "last_fetched_at": at,
                    "content_updated_at": at,
                },
            },
            upsert=True,
        )
