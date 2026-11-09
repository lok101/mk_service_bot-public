from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.ports import (
    PhotoBatchStore,
    PhotoStorage,
    ScopedPhotoStorageFactory,
)
from src.application.shared.outbox_snapshot import snapshot_for_event as _shared_snapshot_for_event
from src.domain.ids import BatchId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_batch import PhotoBatchSnapshot, StoredPhotoRef


@beartype
def snapshot_for_event(
    photo_batch_store: PhotoBatchStore,
    *,
    event_id: str,
    batch_id: BatchId,
) -> PhotoBatchSnapshot:
    return _shared_snapshot_for_event(
        event_id=event_id,
        primary_lookup=photo_batch_store.get_by_event_id,
        fallback_lookup=lambda: photo_batch_store.get_by_batch_id(batch_id),
        not_found_error=lambda evt: NonRetryableOutboxError(
            f"Photo batch snapshot was not found for event {evt}",
        ),
    )


@beartype
def _stored_files_complete(snapshot: PhotoBatchSnapshot) -> bool:
    if not snapshot.stored_files:
        return False
    return all(item.content_hash for item in snapshot.stored_files)


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosOutboxHandler:
    photo_batch_store: PhotoBatchStore
    photo_downloader: PhotoDownloaderRef
    photo_storage: PhotoStorage
    service_timezone: ZoneInfo
    scoped_storage_factory: ScopedPhotoStorageFactory
    key_prefix: str = ""

    @beartype
    async def process(self, event: PhotosSubmitted) -> None:
        snapshot = snapshot_for_event(
            self.photo_batch_store,
            event_id=event.event_id.value,
            batch_id=event.batch_id,
        )
        if _stored_files_complete(snapshot):
            return

        storage = self.scoped_storage_factory(
            self.photo_storage,
            snapshot=snapshot,
            service_timezone=self.service_timezone,
            key_prefix=self.key_prefix,
        )

        stored_files: list[StoredPhotoRef] = []
        for index, photo in enumerate(snapshot.photos):
            downloaded = await self.photo_downloader.downloader.download(photo.file_id)
            content_hash = hashlib.sha256(downloaded.data).hexdigest()
            storage_key = await storage.save(
                batch_id=snapshot.batch_id,
                index=index,
                data=downloaded.data,
                content_type=downloaded.content_type,
            )
            stored_files.append(
                StoredPhotoRef(
                    index=index,
                    storage_key=storage_key,
                    content_type=downloaded.content_type,
                    size_bytes=len(downloaded.data),
                    content_hash=content_hash,
                ),
            )

        await asyncio.to_thread(
            self.photo_batch_store.update_stored_files,
            snapshot.batch_id,
            tuple(stored_files),
        )
