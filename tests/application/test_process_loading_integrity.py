from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from src.application.photo_batches import snapshot_for_event
from src.application.photo_integrity.duplicate_alert import PhotoIntegrityDuplicateAlerter
from src.application.photo_integrity.notifier_ref import PhotoIntegrityAlertNotifierRef
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
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
    InMemoryTechnicianAccountabilityRepository,
)

_TECH = TechnicianId("tech-a")
_MACHINE = MachineId("vm-01")
_OTHER_MACHINE = MachineId("vm-02")
_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
_HASH = "a" * 64


class _FakeRepo:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name=machine_id.value)

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
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


def _save_batch(
    store: InMemoryPhotoBatchStore,
    *,
    batch_id: str,
    event_id: str,
    file_unique_id: str,
) -> None:
    batch = BatchId(batch_id)
    store.save_pending(
        batch_id=batch,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(PhotoRef(file_id=f"file-{batch_id}", file_unique_id=file_unique_id, message_id=1),),
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
                content_hash=_HASH,
            ),
        ),
    )


def _event(*, batch_id: str, event_id: str, machine_id: MachineId) -> PhotosSubmitted:
    return PhotosSubmitted(
        event_id=EventId(event_id),
        batch_id=BatchId(batch_id),
        technician_id=_TECH,
        machine_id=machine_id,
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )


def _use_case(
    store: InMemoryPhotoBatchStore,
    *,
    alert_notifier: _RecordingAlertNotifier,
) -> ProcessLoadingPhotosIntegrity:
    repository = InMemoryTechnicianAccountabilityRepository(
        event_store=InMemoryTechnicianAccountabilityEventStore(),
    )
    return ProcessLoadingPhotosIntegrity(
        hash_index=InMemoryPhotoContentHashIndex(),
        finding_store=InMemoryPhotoIntegrityFindingStore(),
        accountability=RecordPhotoDuplicateAccountabilityAdapter(
            service=RecordPhotoDuplicateSuspectedService(
                executor=TechnicianAccountabilityExecutor(repository=repository),
            ),
        ),
        photo_batch_store=store,
        alerter=PhotoIntegrityDuplicateAlerter(
            alert_notifier=PhotoIntegrityAlertNotifierRef(alert_notifier),
            vending_machine_repository=_FakeRepo(),
            service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        ),
    )


def _run(
    use_case: ProcessLoadingPhotosIntegrity, store: InMemoryPhotoBatchStore, event: PhotosSubmitted
) -> None:
    snapshot = snapshot_for_event(store, event_id=event.event_id.value, batch_id=event.batch_id)
    asyncio.run(use_case.execute(event=event, snapshot=snapshot))


def test_use_case_first_seen_inserts_hash_without_alert() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-1", event_id="event-1", file_unique_id="unique-1")
    alert_notifier = _RecordingAlertNotifier()
    use_case = _use_case(store, alert_notifier=alert_notifier)

    _run(use_case, store, _event(batch_id="batch-1", event_id="event-1", machine_id=_MACHINE))

    assert use_case.hash_index.find_by_content_hash(_HASH) is not None
    assert alert_notifier.calls == 0


def test_use_case_duplicate_creates_finding_and_alert() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-old", event_id="event-old", file_unique_id="unique-shared")
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-shared")
    alert_notifier = _RecordingAlertNotifier()
    use_case = _use_case(store, alert_notifier=alert_notifier)

    _run(use_case, store, _event(batch_id="batch-old", event_id="event-old", machine_id=_MACHINE))
    _run(
        use_case,
        store,
        _event(batch_id="batch-new", event_id="event-new", machine_id=_OTHER_MACHINE),
    )

    assert alert_notifier.calls == 1
    finding = use_case.finding_store.find_pending(
        batch_id=BatchId("batch-new"),
        photo_index=0,
        content_hash=_HASH,
    )
    assert finding is not None
    assert finding.alert_sent_at is not None


def test_use_case_offloads_mark_alert_sent_and_get_by_batch_id_to_thread() -> None:
    store = InMemoryPhotoBatchStore()
    _save_batch(store, batch_id="batch-old", event_id="event-old", file_unique_id="unique-shared")
    _save_batch(store, batch_id="batch-new", event_id="event-new", file_unique_id="unique-shared")
    alert_notifier = _RecordingAlertNotifier()
    use_case = _use_case(store, alert_notifier=alert_notifier)

    offloaded: list[str] = []
    real_to_thread = asyncio.to_thread

    async def _record(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        offloaded.append(getattr(fn, "__name__", repr(fn)))
        return await real_to_thread(fn, *args, **kwargs)

    with patch(
        "src.application.photo_integrity.process_loading_integrity.asyncio.to_thread",
        new=AsyncMock(side_effect=_record),
    ):
        _run(
            use_case,
            store,
            _event(batch_id="batch-old", event_id="event-old", machine_id=_MACHINE),
        )
        _run(
            use_case,
            store,
            _event(batch_id="batch-new", event_id="event-new", machine_id=_OTHER_MACHINE),
        )

    assert "mark_alert_sent" in offloaded
    assert "get_by_batch_id" in offloaded
