from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import PhotoRef, StoredPhotoRef
from src.infrastructure.mongodb.photo_batches import MongoPhotoBatchStore

_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def test_mongodb_photo_batches_round_trip_proxy_and_hash() -> None:
    collection = mongomock.MongoClient().db.photo_batches
    store = MongoPhotoBatchStore.from_collection(collection)
    batch_id = BatchId("batch-mongo-1")
    store.save_pending(
        batch_id=batch_id,
        purpose="loading",
        technician_id=TechnicianId("tech-1"),
        machine_id=MachineId("vm-1"),
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id="file-1",
                file_unique_id="unique-1",
                message_id=1,
            ),
        ),
    )
    store.mark_accepted(batch_id, event_id="event-1", occurred_at=_SUBMITTED_AT)
    store.update_stored_files(
        batch_id,
        (
            StoredPhotoRef(
                index=0,
                storage_key="s3://bucket/key.jpg",
                content_type="image/jpeg",
                size_bytes=100,
                content_hash="a" * 64,
            ),
        ),
    )
    store.update_proxy_message_ids(batch_id, (10, 11))

    snapshot = store.get_by_batch_id(batch_id)
    assert snapshot is not None
    assert snapshot.stored_files[0].content_hash == "a" * 64
    assert snapshot.proxy_message_ids == (10, 11)
