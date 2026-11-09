from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.application.photo_integrity.notifier_ref import PhotoIntegrityAlertNotifierRef
from src.application.photo_integrity.ports import PhotoContentHashEntry
from src.application.shared.display_names import (
    machine_display_name,
    technician_display_name,
)
from src.domain.calendar import calendar_day_in_timezone
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_integrity import PhotoIntegrityFinding


@beartype
@dataclass(frozen=True, slots=True)
class PhotoIntegrityDuplicateAlerter:
    alert_notifier: PhotoIntegrityAlertNotifierRef
    vending_machine_repository: VendingMachineRepository
    service_timezone: ZoneInfo

    @beartype
    async def notify(
        self,
        *,
        event: PhotosSubmitted,
        finding: PhotoIntegrityFinding,
        matched: PhotoContentHashEntry,
        new_photo_file_id: str,
        matched_photo_file_id: str | None,
    ) -> None:
        new_day = calendar_day_in_timezone(
            event.submitted_at,
            self.service_timezone,
        ).strftime("%d.%m.%Y")
        matched_day = calendar_day_in_timezone(
            matched.first_submitted_at,
            self.service_timezone,
        ).strftime("%d.%m.%Y")

        await self.alert_notifier.notifier.notify_duplicate_suspected(
            finding=finding,
            new_photo_file_id=new_photo_file_id,
            matched_photo_file_id=matched_photo_file_id,
            matched_storage_key=matched.storage_key,
            new_calendar_day_label=new_day,
            matched_calendar_day_label=matched_day,
            new_technician_display_name=technician_display_name(
                self.vending_machine_repository,
                event.technician_id,
                fallback=event.technician_id.value,
            ),
            matched_technician_display_name=technician_display_name(
                self.vending_machine_repository,
                matched.first_technician_id,
                fallback=matched.first_technician_id.value,
            ),
            new_machine_display_name=machine_display_name(
                self.vending_machine_repository,
                event.machine_id,
            ),
            matched_machine_display_name=machine_display_name(
                self.vending_machine_repository,
                matched.first_machine_id,
            ),
        )
