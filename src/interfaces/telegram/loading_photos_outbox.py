from __future__ import annotations

import asyncio
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.application.photo_batches import LoadingPhotosChatNotifierRef, snapshot_for_event
from src.application.photo_batches.ports import PhotoBatchStore
from src.application.shared.display_names import (
    machine_display_name,
    technician_display_name,
)
from src.domain.calendar import operational_day
from src.domain.machine_operations.events import PhotosSubmitted


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosTelegramOutboxHandler:
    photo_batch_store: PhotoBatchStore
    notifier: LoadingPhotosChatNotifierRef
    vending_machine_repository: VendingMachineRepository
    service_timezone: ZoneInfo
    day_end_hour: int = 6
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
        if snapshot.proxy_message_ids:
            return

        machine_display = await asyncio.to_thread(
            machine_display_name,
            self.vending_machine_repository,
            event.machine_id,
        )
        technician_display = await asyncio.to_thread(
            technician_display_name,
            self.vending_machine_repository,
            event.technician_id,
            fallback=event.technician_id.value,
        )
        calendar_day_label = operational_day(
            event.submitted_at,
            self.service_timezone,
            self.day_end_hour,
        ).strftime("%d.%m.%Y")

        message_ids = await self.notifier.notifier.notify_batch(
            snapshot=snapshot,
            technician_display_name=technician_display,
            machine_display_name=machine_display,
            calendar_day_label=calendar_day_label,
        )
        if not message_ids:
            return

        await asyncio.to_thread(
            self.photo_batch_store.update_proxy_message_ids,
            snapshot.batch_id,
            message_ids,
        )
