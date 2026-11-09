from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.photo_batch import PhotoBatchSnapshot


@runtime_checkable
class LoadingPhotosChatNotifier(Protocol):
    @beartype
    async def notify_batch(
        self,
        *,
        snapshot: PhotoBatchSnapshot,
        technician_display_name: str,
        machine_display_name: str,
        calendar_day_label: str,
    ) -> tuple[int, ...]: ...
