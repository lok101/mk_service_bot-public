from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.application.photo_integrity.duplicate_alert import PhotoIntegrityDuplicateAlerter
from src.application.photo_integrity.notifier_ref import PhotoIntegrityAlertNotifierRef
from src.application.photo_integrity.ports import PhotoContentHashEntry
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, EventId, FindingId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.models import VendingMachine
from src.domain.photo_integrity import PhotoIntegrityFinding

_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
_MATCHED_AT = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


class _SplitTechnicianNameRepository:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name=machine_id.value)

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        return "Assigned On Machine"

    def find_technician_display_name(
        self,
        technician_id: TechnicianId,
    ) -> str | None:
        if technician_id.value == "tech-new":
            return "New Submitter"
        if technician_id.value == "tech-original":
            return "Original Submitter"
        return None

    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


class _RecordingAlertNotifier:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, object] | None = None

    async def notify_duplicate_suspected(self, **kwargs: object) -> None:
        self.last_kwargs = kwargs


def test_duplicate_alert_uses_submitter_display_names() -> None:
    notifier = _RecordingAlertNotifier()
    alerter = PhotoIntegrityDuplicateAlerter(
        alert_notifier=PhotoIntegrityAlertNotifierRef(notifier),
        vending_machine_repository=_SplitTechnicianNameRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
    )
    event = PhotosSubmitted(
        event_id=EventId("event-1"),
        batch_id=BatchId("batch-new"),
        technician_id=TechnicianId("tech-new"),
        machine_id=MachineId("vm-new"),
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )
    matched = PhotoContentHashEntry(
        content_hash="a" * 64,
        telegram_file_unique_id="unique-old",
        first_batch_id=BatchId("batch-old"),
        first_technician_id=TechnicianId("tech-original"),
        first_machine_id=MachineId("vm-old"),
        first_submitted_at=_MATCHED_AT,
        storage_key="memory://old",
        photo_index=0,
    )
    finding = PhotoIntegrityFinding(
        finding_id=FindingId("finding-1"),
        status="pending_review",
        new_batch_id=event.batch_id,
        matched_batch_id=matched.first_batch_id,
        technician_id=event.technician_id,
        content_hash=matched.content_hash,
        photo_index=0,
        detected_at=_SUBMITTED_AT,
    )

    asyncio.run(
        alerter.notify(
            event=event,
            finding=finding,
            matched=matched,
            new_photo_file_id="file-new",
            matched_photo_file_id="file-old",
        )
    )

    assert notifier.last_kwargs is not None
    assert notifier.last_kwargs["new_technician_display_name"] == "New Submitter"
    assert notifier.last_kwargs["matched_technician_display_name"] == "Original Submitter"
