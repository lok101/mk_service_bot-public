from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.visit_photo_grouping import GroupingBatchView, GroupingStoredFile
from src.domain.ids import BatchId
from src.domain.photo_batch import PhotoBatchSnapshot


@runtime_checkable
class PhotoBatchLookup(Protocol):
    @beartype
    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None: ...


@beartype
class PhotoBatchGroupingReader:
    def __init__(self, store: PhotoBatchLookup) -> None:
        self._store = store

    @beartype
    def get(self, batch_id: str) -> GroupingBatchView | None:
        snapshot = self._store.get_by_batch_id(BatchId(batch_id))
        if snapshot is None:
            return None
        return GroupingBatchView(
            batch_id=snapshot.batch_id.value,
            machine_id=snapshot.machine_id.value,
            status=snapshot.status,
            files=tuple(
                GroupingStoredFile(
                    index=stored.index,
                    storage_key=stored.storage_key,
                    content_type=stored.content_type,
                    content_hash=stored.content_hash,
                )
                for stored in snapshot.stored_files
            ),
        )
