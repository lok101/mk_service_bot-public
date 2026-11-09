from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import BatchId, FindingId, MachineId, TechnicianId
from src.domain.photo_integrity import PhotoIntegrityFinding


@beartype
@dataclass(frozen=True, slots=True)
class PhotoContentHashEntry:
    content_hash: str
    telegram_file_unique_id: str
    first_batch_id: BatchId
    first_technician_id: TechnicianId
    first_machine_id: MachineId
    first_submitted_at: datetime
    storage_key: str
    photo_index: int


@runtime_checkable
class PhotoContentHashIndex(Protocol):
    @beartype
    def find_by_content_hash(self, content_hash: str) -> PhotoContentHashEntry | None: ...

    @beartype
    def find_by_file_unique_id(self, file_unique_id: str) -> PhotoContentHashEntry | None: ...

    @beartype
    def insert_first_seen(self, entry: PhotoContentHashEntry) -> bool: ...


@runtime_checkable
class PhotoIntegrityFindingStore(Protocol):
    @beartype
    def get_by_finding_id(self, finding_id: str) -> PhotoIntegrityFinding | None: ...

    @beartype
    def find_pending(
        self,
        *,
        batch_id: BatchId,
        photo_index: int,
        content_hash: str,
    ) -> PhotoIntegrityFinding | None: ...

    @beartype
    def save(self, finding: PhotoIntegrityFinding) -> None: ...

    @beartype
    def mark_alert_sent(self, finding_id: FindingId, sent_at: datetime) -> None: ...


@runtime_checkable
class PhotoIntegrityAlertNotifier(Protocol):
    @beartype
    async def notify_duplicate_suspected(
        self,
        *,
        finding: PhotoIntegrityFinding,
        new_photo_file_id: str,
        matched_photo_file_id: str | None,
        matched_storage_key: str,
        new_calendar_day_label: str,
        matched_calendar_day_label: str,
        new_technician_display_name: str,
        matched_technician_display_name: str,
        new_machine_display_name: str,
        matched_machine_display_name: str,
    ) -> None: ...


@runtime_checkable
class PhotoDuplicateAccountabilityRecorder(Protocol):
    def record_duplicate_suspected(
        self,
        *,
        technician_id: TechnicianId,
        finding_id: FindingId,
        new_batch_id: BatchId,
        matched_batch_id: BatchId,
        new_machine_id: MachineId,
        matched_machine_id: MachineId,
        content_hash: str,
        photo_index: int,
        detected_at: datetime,
    ) -> None: ...
