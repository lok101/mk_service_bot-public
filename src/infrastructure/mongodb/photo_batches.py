from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from src.config.mongodb import MongoSettings
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import (
    PhotoBatchSnapshot,
    PhotoPurpose,
    PhotoRef,
    StoredPhotoRef,
    accept_snapshot,
    attach_proxy_message_ids,
    attach_stored_files,
    create_pending_snapshot,
    reject_snapshot,
)
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class PhotoBatchesCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> object: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoPhotoBatchStore:
    _collection: PhotoBatchesCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: PhotoBatchesCollection,
    ) -> MongoPhotoBatchStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoPhotoBatchStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.photo_batches_collection,
            owner="MongoPhotoBatchStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            "batch_id",
            unique=True,
            name="photo_batch_id_unique",
        )
        self._collection.create_index(
            "event_id",
            unique=True,
            sparse=True,
            name="photo_batch_event_id_unique",
        )
        self._collection.create_index("submitted_at", name="photo_batch_submitted_at")
        self._collection.create_index(
            [("machine_id", 1), ("submitted_at", -1)],
            name="photo_batch_machine_submitted_at",
        )
        self._collection.create_index(
            [("technician_id", 1), ("submitted_at", -1)],
            name="photo_batch_technician_submitted_at",
        )

    @beartype
    def save_pending(
        self,
        *,
        batch_id: BatchId,
        purpose: PhotoPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        photos: tuple[PhotoRef, ...],
    ) -> PhotoBatchSnapshot:
        existing = self.get_by_batch_id(batch_id)
        if existing is not None:
            resolved = self._resolve_existing_for_save_pending(
                existing,
                purpose=purpose,
                technician_id=technician_id,
                machine_id=machine_id,
                submitted_at=submitted_at,
                photos=photos,
            )
            if resolved is not None:
                return resolved

        document = _snapshot_to_document(
            create_pending_snapshot(
                batch_id=batch_id,
                purpose=purpose,
                technician_id=technician_id,
                machine_id=machine_id,
                submitted_at=submitted_at,
                photos=photos,
            ),
        )
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError:
            existing = self.get_by_batch_id(batch_id)
            if existing is None:
                raise
            resolved = self._resolve_existing_for_save_pending(
                existing,
                purpose=purpose,
                technician_id=technician_id,
                machine_id=machine_id,
                submitted_at=submitted_at,
                photos=photos,
            )
            if resolved is not None:
                return resolved
            return existing

        return _document_to_snapshot(document)

    @beartype
    def _resolve_existing_for_save_pending(
        self,
        existing: PhotoBatchSnapshot,
        *,
        purpose: PhotoPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        photos: tuple[PhotoRef, ...],
    ) -> PhotoBatchSnapshot | None:
        if existing.status == "accepted":
            return existing
        # pending: last-write-wins refresh of the in-flight payload; rejected: reactivate.
        if existing.status in {"pending", "rejected"}:
            return self._refresh_to_pending(
                existing.batch_id,
                purpose=purpose,
                technician_id=technician_id,
                machine_id=machine_id,
                submitted_at=submitted_at,
                photos=photos,
            )
        return None

    @beartype
    def _refresh_to_pending(
        self,
        batch_id: BatchId,
        *,
        purpose: PhotoPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        photos: tuple[PhotoRef, ...],
    ) -> PhotoBatchSnapshot:
        snapshot = create_pending_snapshot(
            batch_id=batch_id,
            purpose=purpose,
            technician_id=technician_id,
            machine_id=machine_id,
            submitted_at=submitted_at,
            photos=photos,
        )
        self._collection.update_one(
            {"batch_id": batch_id.value},
            {"$set": _snapshot_to_document(snapshot)},
        )
        return self._require_snapshot(batch_id)

    @beartype
    def mark_accepted(
        self,
        batch_id: BatchId,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = accept_snapshot(
            snapshot,
            event_id=event_id,
            occurred_at=occurred_at,
        )
        self._collection.update_one(
            {"batch_id": batch_id.value},
            {"$set": _snapshot_to_document(updated)},
        )
        return updated

    @beartype
    def mark_rejected(
        self,
        batch_id: BatchId,
        *,
        reason: str,
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = reject_snapshot(snapshot, reason=reason)
        self._collection.update_one(
            {"batch_id": batch_id.value},
            {"$set": _snapshot_to_document(updated)},
        )
        return updated

    @beartype
    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None:
        document = self._collection.find_one({"batch_id": batch_id.value})
        if document is None:
            return None
        return _document_to_snapshot(document)

    @beartype
    def get_by_event_id(self, event_id: str) -> PhotoBatchSnapshot | None:
        document = self._collection.find_one({"event_id": event_id})
        if document is None:
            return None
        return _document_to_snapshot(document)

    @beartype
    def update_stored_files(
        self,
        batch_id: BatchId,
        stored_files: tuple[StoredPhotoRef, ...],
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = attach_stored_files(snapshot, stored_files)
        self._collection.update_one(
            {"batch_id": batch_id.value},
            {"$set": {"stored_files": [_stored_photo_to_document(item) for item in stored_files]}},
        )
        return updated

    @beartype
    def update_proxy_message_ids(
        self,
        batch_id: BatchId,
        message_ids: tuple[int, ...],
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = attach_proxy_message_ids(snapshot, message_ids)
        self._collection.update_one(
            {"batch_id": batch_id.value},
            {"$set": {"telegram_proxy_message_ids": list(message_ids)}},
        )
        return updated

    @beartype
    def _require_snapshot(self, batch_id: BatchId) -> PhotoBatchSnapshot:
        snapshot = self.get_by_batch_id(batch_id)
        if snapshot is None:
            raise ValueError(f"Photo batch {batch_id.value!r} was not found")
        return snapshot


@beartype
def _photo_ref_to_document(photo: PhotoRef) -> dict[str, Any]:
    document: dict[str, Any] = {
        "file_id": photo.file_id,
        "file_unique_id": photo.file_unique_id,
        "message_id": photo.message_id,
    }
    if photo.media_group_id is not None:
        document["media_group_id"] = photo.media_group_id
    return document


@beartype
def _stored_photo_to_document(stored: StoredPhotoRef) -> dict[str, Any]:
    document: dict[str, Any] = {
        "index": stored.index,
        "storage_key": stored.storage_key,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
    }
    if stored.content_hash:
        document["content_hash"] = stored.content_hash
    return document


@beartype
def _snapshot_to_document(snapshot: PhotoBatchSnapshot) -> dict[str, Any]:
    document: dict[str, Any] = {
        "batch_id": snapshot.batch_id.value,
        "purpose": snapshot.purpose,
        "technician_id": snapshot.technician_id.value,
        "machine_id": snapshot.machine_id.value,
        "submitted_at": snapshot.submitted_at,
        "photos": [_photo_ref_to_document(photo) for photo in snapshot.photos],
        "status": snapshot.status,
        "stored_files": [_stored_photo_to_document(item) for item in snapshot.stored_files],
        "telegram_proxy_message_ids": list(snapshot.proxy_message_ids),
    }
    if snapshot.event_id is not None:
        document["event_id"] = snapshot.event_id
    if snapshot.occurred_at is not None:
        document["occurred_at"] = snapshot.occurred_at
    if snapshot.rejection_reason is not None:
        document["rejection_reason"] = snapshot.rejection_reason
    return document


@beartype
def _document_to_snapshot(document: dict[str, Any]) -> PhotoBatchSnapshot:
    batch_id_raw = document.get("batch_id")
    purpose = document.get("purpose")
    technician_id = document.get("technician_id")
    machine_id = document.get("machine_id")
    submitted_at = document.get("submitted_at")
    status = document.get("status")
    if (
        not isinstance(batch_id_raw, str)
        or purpose != "loading"
        or not isinstance(technician_id, str)
        or not isinstance(machine_id, str)
        or not isinstance(submitted_at, datetime)
        or status not in {"pending", "accepted", "rejected"}
    ):
        raise ValueError("Photo batch document has invalid shape")

    photos = _document_to_photos(document)
    event_id = document.get("event_id")
    occurred_at = document.get("occurred_at")
    rejection_reason = document.get("rejection_reason")
    stored_files = _document_to_stored_files(document)
    proxy_message_ids = _document_to_proxy_message_ids(document)

    return PhotoBatchSnapshot(
        batch_id=BatchId(batch_id_raw),
        purpose="loading",
        technician_id=TechnicianId(technician_id),
        machine_id=MachineId(machine_id),
        submitted_at=submitted_at,
        photos=photos,
        status=status,
        event_id=event_id if isinstance(event_id, str) else None,
        occurred_at=occurred_at if isinstance(occurred_at, datetime) else None,
        stored_files=stored_files,
        proxy_message_ids=proxy_message_ids,
        rejection_reason=(rejection_reason if isinstance(rejection_reason, str) else None),
    )


@beartype
def _document_to_photos(document: dict[str, Any]) -> tuple[PhotoRef, ...]:
    raw_photos = document.get("photos")
    if not isinstance(raw_photos, list) or not raw_photos:
        raise ValueError("Photo batch photos must be a non-empty list")

    photos: list[PhotoRef] = []
    for raw in raw_photos:
        if not isinstance(raw, dict):
            raise ValueError("Photo batch photo entry must be an object")
        file_id = raw.get("file_id")
        file_unique_id = raw.get("file_unique_id")
        message_id = raw.get("message_id")
        media_group_id = raw.get("media_group_id")
        if (
            not isinstance(file_id, str)
            or not isinstance(file_unique_id, str)
            or not isinstance(message_id, int)
        ):
            raise ValueError("Photo batch photo entry has invalid shape")
        photos.append(
            PhotoRef(
                file_id=file_id,
                file_unique_id=file_unique_id,
                message_id=message_id,
                media_group_id=(media_group_id if isinstance(media_group_id, str) else None),
            ),
        )
    return tuple(photos)


@beartype
def _document_to_stored_files(document: dict[str, Any]) -> tuple[StoredPhotoRef, ...]:
    raw_files = document.get("stored_files")
    if raw_files is None:
        return ()
    if not isinstance(raw_files, list):
        raise ValueError("Photo batch stored_files must be a list")

    stored: list[StoredPhotoRef] = []
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValueError("Photo batch stored file entry must be an object")
        index = raw.get("index")
        storage_key = raw.get("storage_key")
        content_type = raw.get("content_type")
        size_bytes = raw.get("size_bytes")
        content_hash = raw.get("content_hash", "")
        if (
            not isinstance(index, int)
            or not isinstance(storage_key, str)
            or not isinstance(content_type, str)
            or not isinstance(size_bytes, int)
        ):
            raise ValueError("Photo batch stored file entry has invalid shape")
        stored.append(
            StoredPhotoRef(
                index=index,
                storage_key=storage_key,
                content_type=content_type,
                size_bytes=size_bytes,
                content_hash=content_hash if isinstance(content_hash, str) else "",
            ),
        )
    return tuple(stored)


@beartype
def _document_to_proxy_message_ids(document: dict[str, Any]) -> tuple[int, ...]:
    raw_ids = document.get("telegram_proxy_message_ids", [])
    if raw_ids is None:
        return ()
    if not isinstance(raw_ids, list):
        raise ValueError("telegram_proxy_message_ids must be a list")
    message_ids: list[int] = []
    for item in raw_ids:
        if not isinstance(item, int):
            raise ValueError("telegram_proxy_message_ids entries must be integers")
        message_ids.append(item)
    return tuple(message_ids)
