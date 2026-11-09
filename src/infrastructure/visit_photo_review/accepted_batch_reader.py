from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.visit_photo_review.ports import AcceptedBatch, AcceptedPhotoFile
from src.domain.ids import BatchId
from src.domain.photo_batch import PhotoBatchSnapshot


@runtime_checkable
class PhotoBatchLookup(Protocol):
    @beartype
    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None: ...


@beartype
class AcceptedBatchReaderAdapter:
    def __init__(self, store: PhotoBatchLookup) -> None:
        self._store = store

    @beartype
    def get(self, batch_id: str) -> AcceptedBatch | None:
        snapshot = self._store.get_by_batch_id(BatchId(batch_id))
        if snapshot is None or snapshot.status != "accepted":
            return None
        occurred_at = snapshot.occurred_at
        if occurred_at is None:
            return None
        return AcceptedBatch(
            batch_id=snapshot.batch_id.value,
            machine_id=snapshot.machine_id.value,
            technician_id=snapshot.technician_id.value,
            occurred_at=occurred_at,
            files=tuple(
                AcceptedPhotoFile(
                    index=stored.index,
                    content_type=stored.content_type,
                    storage_key=stored.storage_key,
                )
                for stored in snapshot.stored_files
            ),
        )
