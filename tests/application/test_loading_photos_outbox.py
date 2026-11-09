from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.outbox_handler import LoadingPhotosOutboxHandler
from src.application.photo_batches.ports import PhotoStorage
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.stubs import (
    InMemoryPhotoStorage,
    StubTelegramPhotoDownloader,
)


@beartype
def _identity_scoped_storage_factory(
    inner: PhotoStorage,
    *,
    snapshot: PhotoBatchSnapshot,
    service_timezone: ZoneInfo,
    key_prefix: str = "",
) -> PhotoStorage:
    del snapshot, service_timezone, key_prefix
    return inner


_BATCH_ID = BatchId("batch-outbox-1")
_EVENT_ID = EventId("event-outbox-1")
_TECH = TechnicianId("tech-a")
_MACHINE = MachineId("vm-01")
_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def test_loading_photos_outbox_persists_stored_files() -> None:
    store = InMemoryPhotoBatchStore()
    store.save_pending(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id="file-1",
                file_unique_id="u-1",
                message_id=1,
            ),
            PhotoRef(
                file_id="file-2",
                file_unique_id="u-2",
                message_id=2,
            ),
        ),
    )
    store.mark_accepted(
        _BATCH_ID,
        event_id=_EVENT_ID.value,
        occurred_at=_SUBMITTED_AT,
    )
    storage = InMemoryPhotoStorage()
    handler = LoadingPhotosOutboxHandler(
        photo_batch_store=store,
        photo_downloader=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
        photo_storage=storage,
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        scoped_storage_factory=_identity_scoped_storage_factory,
    )
    event = PhotosSubmitted(
        event_id=_EVENT_ID,
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=2,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )

    asyncio.run(handler.process(event))

    snapshot = store.get_by_event_id(_EVENT_ID.value)
    assert snapshot is not None
    assert len(snapshot.stored_files) == 2
    assert snapshot.stored_files[0].storage_key.startswith("memory://")
    assert len(snapshot.stored_files[0].content_hash) == 64


def test_loading_photos_outbox_is_idempotent() -> None:
    store = InMemoryPhotoBatchStore()
    store.save_pending(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id="file-1",
                file_unique_id="u-1",
                message_id=1,
            ),
        ),
    )
    store.mark_accepted(
        _BATCH_ID,
        event_id=_EVENT_ID.value,
        occurred_at=_SUBMITTED_AT,
    )
    storage = InMemoryPhotoStorage()
    handler = LoadingPhotosOutboxHandler(
        photo_batch_store=store,
        photo_downloader=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
        photo_storage=storage,
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        scoped_storage_factory=_identity_scoped_storage_factory,
    )
    event = PhotosSubmitted(
        event_id=_EVENT_ID,
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )

    asyncio.run(handler.process(event))
    asyncio.run(handler.process(event))

    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert len(snapshot.stored_files) == 1
