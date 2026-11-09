from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef, StoredPhotoRef
from src.infrastructure.visit_photo_review.accepted_batch_reader import (
    AcceptedBatchReaderAdapter,
)

_OCCURRED_AT = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 23, 3, 0, tzinfo=UTC)


class _MemoryBatchStore:
    def __init__(self, snapshot: PhotoBatchSnapshot) -> None:
        self._snapshot = snapshot

    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None:
        if self._snapshot.batch_id.value != batch_id.value:
            return None
        return self._snapshot


def _store_with_accepted() -> _MemoryBatchStore:
    return _MemoryBatchStore(
        PhotoBatchSnapshot(
            batch_id=BatchId("batch-1"),
            purpose="loading",
            technician_id=TechnicianId("t-1"),
            machine_id=MachineId("m-1"),
            submitted_at=_SUBMITTED_AT,
            photos=(PhotoRef(file_id="f1", file_unique_id="u1", message_id=1),),
            status="accepted",
            event_id="evt-1",
            occurred_at=_OCCURRED_AT,
            stored_files=(
                StoredPhotoRef(
                    index=0,
                    storage_key="photos/batch-1/0.jpg",
                    content_type="image/jpeg",
                    size_bytes=10,
                ),
            ),
        )
    )


def _store_with_pending() -> _MemoryBatchStore:
    return _MemoryBatchStore(
        PhotoBatchSnapshot(
            batch_id=BatchId("batch-1"),
            purpose="loading",
            technician_id=TechnicianId("t-1"),
            machine_id=MachineId("m-1"),
            submitted_at=_SUBMITTED_AT,
            photos=(PhotoRef(file_id="f1", file_unique_id="u1", message_id=1),),
            status="pending",
        )
    )


def test_accepted_batch_reader_maps_stored_file() -> None:
    reader = AcceptedBatchReaderAdapter(_store_with_accepted())
    batch = reader.get("batch-1")
    assert batch is not None
    assert batch.files[0].index == 0
    assert batch.files[0].content_type == "image/jpeg"
    assert batch.machine_id == "m-1"


def test_accepted_batch_reader_returns_none_when_not_accepted() -> None:
    reader = AcceptedBatchReaderAdapter(_store_with_pending())
    assert reader.get("batch-1") is None
