from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import (
    PhotoBatchSnapshot,
    PhotoPurpose,
    PhotoRef,
    StoredPhotoRef,
)


@beartype
@dataclass(frozen=True, slots=True)
class DownloadedPhoto:
    data: bytes
    content_type: str


@runtime_checkable
class PhotoBatchStore(Protocol):
    @beartype
    def save_pending(
        self,
        *,
        batch_id: BatchId,
        purpose: PhotoPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        photos: tuple[PhotoRef, ...],
    ) -> PhotoBatchSnapshot: ...

    @beartype
    def mark_accepted(
        self,
        batch_id: BatchId,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> PhotoBatchSnapshot: ...

    @beartype
    def mark_rejected(
        self,
        batch_id: BatchId,
        *,
        reason: str,
    ) -> PhotoBatchSnapshot: ...

    @beartype
    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None: ...

    @beartype
    def get_by_event_id(self, event_id: str) -> PhotoBatchSnapshot | None: ...

    @beartype
    def update_stored_files(
        self,
        batch_id: BatchId,
        stored_files: tuple[StoredPhotoRef, ...],
    ) -> PhotoBatchSnapshot: ...

    @beartype
    def update_proxy_message_ids(
        self,
        batch_id: BatchId,
        message_ids: tuple[int, ...],
    ) -> PhotoBatchSnapshot: ...


@runtime_checkable
class TelegramPhotoDownloader(Protocol):
    @beartype
    async def download(self, file_id: str) -> DownloadedPhoto: ...


@runtime_checkable
class PhotoStorage(Protocol):
    @beartype
    async def save(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
    ) -> str: ...

    @beartype
    async def get_bytes(self, storage_key: str) -> bytes: ...

    @beartype
    async def delete(self, storage_key: str) -> None: ...


@runtime_checkable
class ScopedPhotoStorageFactory(Protocol):
    @beartype
    def __call__(
        self,
        inner: PhotoStorage,
        *,
        snapshot: PhotoBatchSnapshot,
        service_timezone: ZoneInfo,
        key_prefix: str = "",
    ) -> PhotoStorage: ...


@runtime_checkable
class BatchContextPhotoStorage(Protocol):
    @beartype
    async def save_for_batch(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
        technician_id: TechnicianId,
        machine_id: MachineId,
        submitted_at: datetime,
        service_timezone: ZoneInfo,
        key_prefix: str,
    ) -> str: ...
