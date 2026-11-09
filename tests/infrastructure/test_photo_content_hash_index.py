from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest

from src.application.photo_integrity.ports import PhotoContentHashEntry
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.infrastructure.mongodb.photo_content_hashes import MongoPhotoContentHashIndex

_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
_ENTRY = PhotoContentHashEntry(
    content_hash="hash-1",
    telegram_file_unique_id="unique-1",
    first_batch_id=BatchId("batch-1"),
    first_technician_id=TechnicianId("tech-1"),
    first_machine_id=MachineId("vm-1"),
    first_submitted_at=_SUBMITTED_AT,
    storage_key="s3://bucket/key",
    photo_index=0,
)


@pytest.fixture
def hash_index() -> MongoPhotoContentHashIndex:
    collection = mongomock.MongoClient().db.photo_content_hashes
    return MongoPhotoContentHashIndex.from_collection(collection)


def test_insert_first_seen_and_lookup(hash_index: MongoPhotoContentHashIndex) -> None:
    assert hash_index.insert_first_seen(_ENTRY) is True
    assert hash_index.find_by_content_hash("hash-1") is not None
    assert hash_index.find_by_file_unique_id("unique-1") is not None


def test_insert_first_seen_is_idempotent_on_duplicate_hash(
    hash_index: MongoPhotoContentHashIndex,
) -> None:
    assert hash_index.insert_first_seen(_ENTRY) is True
    assert hash_index.insert_first_seen(_ENTRY) is False
