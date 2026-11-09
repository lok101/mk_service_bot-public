from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_batches.outbox_handler import LoadingPhotosOutboxHandler
from src.application.photo_batches.ports import PhotoStorage
from src.application.photo_integrity import (
    LoadingPhotosIntegrityOutboxHandler,
    PhotoIntegrityAlertNotifierRef,
)
from src.application.photo_integrity.duplicate_alert import PhotoIntegrityDuplicateAlerter
from src.application.photo_integrity.process_loading_integrity import (
    ProcessLoadingPhotosIntegrity,
)
from src.application.technician_accountability.executor import TechnicianAccountabilityExecutor
from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.models import VendingMachine
from src.domain.photo_batch import PhotoRef, StoredPhotoRef
from src.infrastructure.composition.record_duplicate_accountability_adapter import (
    RecordPhotoDuplicateAccountabilityAdapter,
)
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.memory_integrity import (
    InMemoryPhotoContentHashIndex,
    InMemoryPhotoIntegrityFindingStore,
)
from src.infrastructure.photo_batches.stubs import (
    InMemoryPhotoStorage,
    StubTelegramPhotoDownloader,
)
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
    InMemoryTechnicianAccountabilityRepository,
)
from src.interfaces.telegram.loading_photos_outbox import LoadingPhotosTelegramOutboxHandler

_BATCH_ID = BatchId("batch-async-1")
_EVENT_ID = EventId("event-async-1")
_TECH = TechnicianId("tech-a")
_MACHINE = MachineId("vm-01")
_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
_HASH = "b" * 64


@beartype
def _identity_scoped_storage_factory(
    inner: PhotoStorage,
    *,
    snapshot: object,
    service_timezone: ZoneInfo,
    key_prefix: str = "",
) -> PhotoStorage:
    del snapshot, service_timezone, key_prefix
    return inner


class _FakeVendingMachineRepository:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name=machine_id.value)

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        return "Иванов И."

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return "Иванов И."

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


class _RecordingTelegramNotifier:
    async def notify_batch(self, **kwargs: object) -> tuple[int, ...]:
        return (101,)


class _NoopAlertNotifier:
    async def notify_duplicate_suspected(self, **kwargs: object) -> None:
        return None


def _photos_event() -> PhotosSubmitted:
    return PhotosSubmitted(
        event_id=_EVENT_ID,
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )


def _save_accepted_batch(store: InMemoryPhotoBatchStore) -> None:
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


def test_loading_photos_outbox_store_update_runs_in_thread() -> None:
    store = InMemoryPhotoBatchStore()
    _save_accepted_batch(store)
    handler = LoadingPhotosOutboxHandler(
        photo_batch_store=store,
        photo_downloader=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
        photo_storage=InMemoryPhotoStorage(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        scoped_storage_factory=_identity_scoped_storage_factory,
    )
    with patch(
        "src.application.photo_batches.outbox_handler.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as to_thread:
        to_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        asyncio.run(handler.process(_photos_event()))
    assert to_thread.await_count >= 1


def test_loading_photos_telegram_repo_runs_in_thread() -> None:
    store = InMemoryPhotoBatchStore()
    _save_accepted_batch(store)
    handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=store,
        notifier=LoadingPhotosChatNotifierRef(_RecordingTelegramNotifier()),
        vending_machine_repository=_FakeVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        enabled=True,
    )
    with patch(
        "src.interfaces.telegram.loading_photos_outbox.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as to_thread:
        to_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        asyncio.run(handler.process(_photos_event()))
    assert to_thread.await_count >= 1


def test_loading_photos_integrity_store_runs_in_thread() -> None:
    store = InMemoryPhotoBatchStore()
    _save_accepted_batch(store)
    store.update_stored_files(
        _BATCH_ID,
        (
            StoredPhotoRef(
                index=0,
                storage_key="memory://batch-async-1/0",
                content_type="image/jpeg",
                size_bytes=10,
                content_hash=_HASH,
            ),
        ),
    )
    process_integrity = ProcessLoadingPhotosIntegrity(
        hash_index=InMemoryPhotoContentHashIndex(),
        finding_store=InMemoryPhotoIntegrityFindingStore(),
        accountability=RecordPhotoDuplicateAccountabilityAdapter(
            service=RecordPhotoDuplicateSuspectedService(
                executor=TechnicianAccountabilityExecutor(
                    repository=InMemoryTechnicianAccountabilityRepository(
                        event_store=InMemoryTechnicianAccountabilityEventStore(),
                    ),
                ),
            ),
        ),
        photo_batch_store=store,
        alerter=PhotoIntegrityDuplicateAlerter(
            alert_notifier=PhotoIntegrityAlertNotifierRef(_NoopAlertNotifier()),
            vending_machine_repository=_FakeVendingMachineRepository(),
            service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        ),
    )
    handler = LoadingPhotosIntegrityOutboxHandler(
        photo_batch_store=store,
        process_integrity=process_integrity,
        enabled=True,
    )
    with patch(
        "src.application.photo_integrity.process_loading_integrity.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as to_thread:
        to_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        asyncio.run(handler.process(_photos_event()))
    assert to_thread.await_count >= 1
