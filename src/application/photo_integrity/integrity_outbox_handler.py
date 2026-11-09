from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.photo_batches import snapshot_for_event
from src.application.photo_batches.ports import PhotoBatchStore
from src.application.photo_integrity.process_loading_integrity import (
    ProcessLoadingPhotosIntegrity,
)
from src.domain.machine_operations.events import PhotosSubmitted


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosIntegrityOutboxHandler:
    photo_batch_store: PhotoBatchStore
    process_integrity: ProcessLoadingPhotosIntegrity
    enabled: bool = True

    @beartype
    async def process(self, event: PhotosSubmitted) -> None:
        if not self.enabled:
            return

        snapshot = snapshot_for_event(
            self.photo_batch_store,
            event_id=event.event_id.value,
            batch_id=event.batch_id,
        )
        if not snapshot.stored_files:
            raise RuntimeError("stored_files are not ready yet")
        if not all(item.content_hash for item in snapshot.stored_files):
            raise RuntimeError("content_hash is not ready yet")

        await self.process_integrity.execute(event=event, snapshot=snapshot)
