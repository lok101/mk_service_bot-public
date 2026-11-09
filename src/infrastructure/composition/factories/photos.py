from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.photo_batches.ports import PhotoBatchStore, PhotoStorage
from src.application.photo_integrity.ports import (
    PhotoContentHashIndex,
    PhotoIntegrityFindingStore,
)
from src.config.settings import Settings
from src.infrastructure.mongodb.photo_batches import MongoPhotoBatchStore
from src.infrastructure.mongodb.photo_content_hashes import MongoPhotoContentHashIndex
from src.infrastructure.mongodb.photo_integrity_findings import MongoPhotoIntegrityFindingStore
from src.infrastructure.photo_batches import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.memory_integrity import (
    InMemoryPhotoContentHashIndex,
    InMemoryPhotoIntegrityFindingStore,
)
from src.infrastructure.photo_batches.s3 import S3PhotoStorage
from src.infrastructure.photo_batches.stubs import InMemoryPhotoStorage


@beartype
def build_photo_batch_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> PhotoBatchStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoPhotoBatchStore.from_settings(mongo, client=client)
    return InMemoryPhotoBatchStore()


@beartype
def build_photo_storage(settings: Settings) -> PhotoStorage:
    storage = settings.object_storage
    if storage.backend == "s3":
        return S3PhotoStorage.from_settings(
            storage,
            service_timezone=settings.service_calendar.zone_info(),
        )
    return InMemoryPhotoStorage()


@beartype
def build_photo_content_hash_index(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> PhotoContentHashIndex:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoPhotoContentHashIndex.from_settings(mongo, client=client)
    return InMemoryPhotoContentHashIndex()


@beartype
def build_photo_integrity_finding_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> PhotoIntegrityFindingStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoPhotoIntegrityFindingStore.from_settings(mongo, client=client)
    return InMemoryPhotoIntegrityFindingStore()
