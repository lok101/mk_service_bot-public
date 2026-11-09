from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.photo_integrity.ports import PhotoContentHashEntry
from src.config.mongodb import MongoSettings
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class PhotoContentHashesCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoPhotoContentHashIndex:
    _collection: PhotoContentHashesCollection

    @classmethod
    @beartype
    def from_collection(
        cls, collection: PhotoContentHashesCollection
    ) -> MongoPhotoContentHashIndex:
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
    ) -> MongoPhotoContentHashIndex:
        collection = resolve_collection(
            settings,
            collection_name=settings.photo_content_hashes_collection,
            owner="MongoPhotoContentHashIndex",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            "content_hash",
            unique=True,
            name="photo_content_hash_unique",
        )
        self._collection.create_index(
            "telegram_file_unique_id",
            name="photo_file_unique_id",
        )

    @beartype
    def find_by_content_hash(self, content_hash: str) -> PhotoContentHashEntry | None:
        document = self._collection.find_one({"content_hash": content_hash})
        if document is None:
            return None
        return _document_to_entry(document)

    @beartype
    def find_by_file_unique_id(self, file_unique_id: str) -> PhotoContentHashEntry | None:
        document = self._collection.find_one({"telegram_file_unique_id": file_unique_id})
        if document is None:
            return None
        return _document_to_entry(document)

    @beartype
    def insert_first_seen(self, entry: PhotoContentHashEntry) -> bool:
        document = _entry_to_document(entry)
        try:
            self._collection.insert_one(document)
            return True
        except DuplicateKeyError:
            return False


@beartype
def _entry_to_document(entry: PhotoContentHashEntry) -> dict[str, Any]:
    return {
        "content_hash": entry.content_hash,
        "telegram_file_unique_id": entry.telegram_file_unique_id,
        "first_batch_id": entry.first_batch_id.value,
        "first_technician_id": entry.first_technician_id.value,
        "first_machine_id": entry.first_machine_id.value,
        "first_submitted_at": entry.first_submitted_at,
        "storage_key": entry.storage_key,
        "photo_index": entry.photo_index,
    }


@beartype
def _document_to_entry(document: dict[str, Any]) -> PhotoContentHashEntry:
    content_hash = document.get("content_hash")
    file_unique_id = document.get("telegram_file_unique_id")
    first_batch_id = document.get("first_batch_id")
    first_technician_id = document.get("first_technician_id")
    first_machine_id = document.get("first_machine_id")
    first_submitted_at = document.get("first_submitted_at")
    storage_key = document.get("storage_key")
    photo_index = document.get("photo_index")
    if (
        not isinstance(content_hash, str)
        or not isinstance(file_unique_id, str)
        or not isinstance(first_batch_id, str)
        or not isinstance(first_technician_id, str)
        or not isinstance(first_machine_id, str)
        or not isinstance(first_submitted_at, datetime)
        or not isinstance(storage_key, str)
        or not isinstance(photo_index, int)
    ):
        raise ValueError("Photo content hash document has invalid shape")
    return PhotoContentHashEntry(
        content_hash=content_hash,
        telegram_file_unique_id=file_unique_id,
        first_batch_id=BatchId(first_batch_id),
        first_technician_id=TechnicianId(first_technician_id),
        first_machine_id=MachineId(first_machine_id),
        first_submitted_at=first_submitted_at,
        storage_key=storage_key,
        photo_index=photo_index,
    )
