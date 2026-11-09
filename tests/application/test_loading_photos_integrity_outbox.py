from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.application.photo_integrity import (
    LoadingPhotosIntegrityOutboxHandler,
    PhotoIntegrityAlertNotifierRef,
    deterministic_photo_integrity_finding_id,
)
from src.application.photo_integrity.duplicate_alert import PhotoIntegrityDuplicateAlerter
from src.application.photo_integrity.ports import PhotoContentHashEntry
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
from src.domain.photo_integrity import PhotoIntegrityFinding
from src.infrastructure.composition.record_duplicate_accountability_adapter import (
    RecordPhotoDuplicateAccountabilityAdapter,
)
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.memory_integrity import (
    InMemoryPhotoContentHashIndex,
    InMemoryPhotoIntegrityFindingStore,
)
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
    InMemoryTechnicianAccountabilityRepository,
)

_TECH = TechnicianId("tech-a")
_MACHINE = MachineId("vm-01")
_OTHER_MACHINE = MachineId("vm-02")
_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
_HASH = "a" * 64


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


class _RecordingAlertNotifier:
    def __init__(self) -> None:
        self.calls = 0

    async def notify_duplicate_suspected(self, **kwargs: object) -> None:
        self.calls += 1


def _build_handler(
    *,
    store: InMemoryPhotoBatchStore,
    alert_notifier: _RecordingAlertNotifier,
    hash_index: InMemoryPhotoContentHashIndex | None = None,
    finding_store: InMemoryPhotoIntegrityFindingStore | None = None,
    accountability_repository: InMemoryTechnicianAccountabilityRepository | None = None,
) -> LoadingPhotosIntegrityOutboxHandler:
    accountability_repository = (
        accountability_repository
        or InMemoryTechnicianAccountabilityRepository(
            event_store=InMemoryTechnicianAccountabilityEventStore(),
        )
    )
    process_integrity = ProcessLoadingPhotosIntegrity(
        hash_index=hash_index or InMemoryPhotoContentHashIndex(),
        finding_store=finding_store or InMemoryPhotoIntegrityFindingStore(),
        accountability=RecordPhotoDuplicateAccountabilityAdapter(
            service=RecordPhotoDuplicateSuspectedService(
                executor=TechnicianAccountabilityExecutor(repository=accountability_repository),
            ),
        ),
        photo_batch_store=store,
        alerter=PhotoIntegrityDuplicateAlerter(
            alert_notifier=PhotoIntegrityAlertNotifierRef(alert_notifier),
            vending_machine_repository=_FakeVendingMachineRepository(),
            service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        ),
    )
    return LoadingPhotosIntegrityOutboxHandler(
        photo_batch_store=store,
        process_integrity=process_integrity,
        enabled=True,
    )


def _save_batch(
    store: InMemoryPhotoBatchStore,
    *,
    batch_id: str,
    event_id: str,
    file_unique_id: str,
    content_hash: str = _HASH,
) -> None:
    batch = BatchId(batch_id)
    store.save_pending(
        batch_id=batch,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id=f"file-{batch_id}",
                file_unique_id=file_unique_id,
                message_id=1,
            ),
        ),
    )
    store.mark_accepted(batch, event_id=event_id, occurred_at=_SUBMITTED_AT)
    store.update_stored_files(
        batch,
        (
            StoredPhotoRef(
                index=0,
                storage_key=f"memory://{batch_id}/0",
                content_type="image/jpeg",
                size_bytes=10,
                content_hash=content_hash,
            ),
        ),
    )


def _duplicate_event(
    *, batch_id: str, event_id: str, machine_id: MachineId = _OTHER_MACHINE
) -> PhotosSubmitted:
    return PhotosSubmitted(
        event_id=EventId(event_id),
        batch_id=BatchId(batch_id),
        technician_id=_TECH,
        machine_id=machine_id,
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )


def test_integrity_first_seen_inserts_hash_without_alert() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-1", event_id="event-1", file_unique_id="unique-1")
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(store=store, alert_notifier=alert_notifier)
    hash_index = handler.process_integrity.hash_index

    asyncio.run(
        handler.process(
            _duplicate_event(batch_id="batch-1", event_id="event-1", machine_id=_MACHINE)
        )
    )

    assert hash_index.find_by_content_hash(_HASH) is not None
    assert hash_index.find_by_file_unique_id("unique-1") is not None
    assert alert_notifier.calls == 0


def test_integrity_duplicate_creates_finding_and_alert() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-old", event_id="event-old", file_unique_id="unique-shared")
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-shared")
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(store=store, alert_notifier=alert_notifier)

    asyncio.run(
        handler.process(
            _duplicate_event(batch_id="batch-old", event_id="event-old", machine_id=_MACHINE)
        )
    )
    asyncio.run(handler.process(_duplicate_event(batch_id="batch-new", event_id="event-new")))

    assert alert_notifier.calls == 1
    finding = handler.process_integrity.finding_store.find_pending(
        batch_id=BatchId("batch-new"),
        photo_index=0,
        content_hash=_HASH,
    )
    assert finding is not None
    assert finding.status == "pending_review"
    assert finding.alert_sent_at is not None


def test_integrity_handler_is_idempotent() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-old", event_id="event-old", file_unique_id="unique-shared")
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-shared")
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(store=store, alert_notifier=alert_notifier)
    event = _duplicate_event(batch_id="batch-old", event_id="event-old", machine_id=_MACHINE)
    duplicate_event = _duplicate_event(batch_id="batch-new", event_id="event-new")

    asyncio.run(handler.process(event))
    asyncio.run(handler.process(duplicate_event))
    asyncio.run(handler.process(duplicate_event))

    assert alert_notifier.calls == 1


def test_integrity_insert_race_treats_loser_as_duplicate() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(
        store, batch_id="batch-winner", event_id="event-winner", file_unique_id="unique-winner"
    )
    _save_batch(
        store, batch_id="batch-loser", event_id="event-loser", file_unique_id="unique-loser"
    )
    hash_index = InMemoryPhotoContentHashIndex()
    hash_index.insert_first_seen(
        PhotoContentHashEntry(
            content_hash=_HASH,
            telegram_file_unique_id="unique-winner",
            first_batch_id=BatchId("batch-winner"),
            first_technician_id=_TECH,
            first_machine_id=_MACHINE,
            first_submitted_at=_SUBMITTED_AT,
            storage_key="memory://batch-winner/0",
            photo_index=0,
        ),
    )
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(store=store, alert_notifier=alert_notifier, hash_index=hash_index)

    asyncio.run(handler.process(_duplicate_event(batch_id="batch-loser", event_id="event-loser")))

    assert alert_notifier.calls == 1
    finding = handler.process_integrity.finding_store.find_pending(
        batch_id=BatchId("batch-loser"),
        photo_index=0,
        content_hash=_HASH,
    )
    assert finding is not None


def test_integrity_retries_alert_when_finding_exists_without_alert_sent() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-old", event_id="event-old", file_unique_id="unique-old")
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-new")
    hash_index = InMemoryPhotoContentHashIndex()
    hash_index.insert_first_seen(
        PhotoContentHashEntry(
            content_hash=_HASH,
            telegram_file_unique_id="unique-old",
            first_batch_id=BatchId("batch-old"),
            first_technician_id=_TECH,
            first_machine_id=_MACHINE,
            first_submitted_at=_SUBMITTED_AT,
            storage_key="memory://batch-old/0",
            photo_index=0,
        ),
    )
    finding_store = InMemoryPhotoIntegrityFindingStore()
    finding_id = deterministic_photo_integrity_finding_id(
        batch_id=BatchId("batch-new"),
        photo_index=0,
        content_hash=_HASH,
    )
    finding_store.save(
        PhotoIntegrityFinding(
            finding_id=finding_id,
            status="pending_review",
            new_batch_id=BatchId("batch-new"),
            matched_batch_id=BatchId("batch-old"),
            technician_id=_TECH,
            content_hash=_HASH,
            photo_index=0,
            detected_at=_SUBMITTED_AT,
        ),
    )
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(
        store=store,
        alert_notifier=alert_notifier,
        hash_index=hash_index,
        finding_store=finding_store,
    )

    asyncio.run(handler.process(_duplicate_event(batch_id="batch-new", event_id="event-new")))

    assert alert_notifier.calls == 1
    updated = finding_store.get_by_finding_id(finding_id.value)
    assert updated is not None
    assert updated.alert_sent_at is not None


def test_integrity_does_not_resend_alert_when_alert_sent_at_set() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-new")
    finding_store = InMemoryPhotoIntegrityFindingStore()
    finding_id = deterministic_photo_integrity_finding_id(
        batch_id=BatchId("batch-new"),
        photo_index=0,
        content_hash=_HASH,
    )
    sent_at = datetime(2026, 6, 5, tzinfo=UTC)
    finding_store.save(
        PhotoIntegrityFinding(
            finding_id=finding_id,
            status="pending_review",
            new_batch_id=BatchId("batch-new"),
            matched_batch_id=BatchId("batch-old"),
            technician_id=_TECH,
            content_hash=_HASH,
            photo_index=0,
            detected_at=_SUBMITTED_AT,
            alert_sent_at=sent_at,
        ),
    )
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(
        store=store, alert_notifier=alert_notifier, finding_store=finding_store
    )

    asyncio.run(handler.process(_duplicate_event(batch_id="batch-new", event_id="event-new")))

    assert alert_notifier.calls == 0


def test_integrity_duplicate_by_content_hash_only() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(
        store,
        batch_id="batch-old",
        event_id="event-old",
        file_unique_id="unique-old",
        content_hash=_HASH,
    )
    _save_batch(
        store,
        batch_id="batch-new",
        event_id="event-new",
        file_unique_id="unique-new",
        content_hash=_HASH,
    )
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(store=store, alert_notifier=alert_notifier)

    asyncio.run(
        handler.process(
            _duplicate_event(batch_id="batch-old", event_id="event-old", machine_id=_MACHINE)
        )
    )
    asyncio.run(handler.process(_duplicate_event(batch_id="batch-new", event_id="event-new")))

    assert alert_notifier.calls == 1


def test_integrity_deterministic_finding_id() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-old", event_id="event-old", file_unique_id="unique-shared")
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-shared")
    accountability_repository = InMemoryTechnicianAccountabilityRepository(
        event_store=InMemoryTechnicianAccountabilityEventStore(),
    )
    alert_notifier = _RecordingAlertNotifier()
    handler = _build_handler(
        store=store,
        alert_notifier=alert_notifier,
        accountability_repository=accountability_repository,
    )
    duplicate_event = _duplicate_event(batch_id="batch-new", event_id="event-new")

    asyncio.run(
        handler.process(
            _duplicate_event(batch_id="batch-old", event_id="event-old", machine_id=_MACHINE)
        )
    )
    asyncio.run(handler.process(duplicate_event))
    asyncio.run(handler.process(duplicate_event))

    expected_id = deterministic_photo_integrity_finding_id(
        batch_id=BatchId("batch-new"),
        photo_index=0,
        content_hash=_HASH,
    )
    finding = handler.process_integrity.finding_store.get_by_finding_id(expected_id.value)
    assert finding is not None
    events = accountability_repository.event_store.get_events_for_technician(_TECH)
    assert len(events) == 1
