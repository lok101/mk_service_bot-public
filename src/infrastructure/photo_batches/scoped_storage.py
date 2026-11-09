from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.photo_batches.ports import BatchContextPhotoStorage, PhotoStorage
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import PhotoBatchSnapshot
from src.infrastructure.photo_batches.s3_keys import build_loading_photo_object_key


@beartype
@dataclass(frozen=True, slots=True)
class ScopedPhotoStorage:
    inner: PhotoStorage
    technician_id: TechnicianId
    machine_id: MachineId
    submitted_at: datetime
    service_timezone: ZoneInfo
    key_prefix: str = ""

    @beartype
    async def save(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
    ) -> str:
        if isinstance(self.inner, BatchContextPhotoStorage):
            return await self.inner.save_for_batch(
                batch_id=batch_id,
                index=index,
                data=data,
                content_type=content_type,
                technician_id=self.technician_id,
                machine_id=self.machine_id,
                submitted_at=self.submitted_at,
                service_timezone=self.service_timezone,
                key_prefix=self.key_prefix,
            )

        return await self.inner.save(
            batch_id=batch_id,
            index=index,
            data=data,
            content_type=content_type,
        )

    @beartype
    async def get_bytes(self, storage_key: str) -> bytes:
        return await self.inner.get_bytes(storage_key)

    @beartype
    async def delete(self, storage_key: str) -> None:
        await self.inner.delete(storage_key)


@beartype
def scoped_photo_storage(
    inner: PhotoStorage,
    *,
    snapshot: PhotoBatchSnapshot,
    service_timezone: ZoneInfo,
    key_prefix: str = "",
) -> PhotoStorage:
    return ScopedPhotoStorage(
        inner=inner,
        technician_id=snapshot.technician_id,
        machine_id=snapshot.machine_id,
        submitted_at=snapshot.submitted_at,
        service_timezone=service_timezone,
        key_prefix=key_prefix,
    )


@beartype
def preview_object_key_for_batch(
    *,
    snapshot: PhotoBatchSnapshot,
    service_timezone: ZoneInfo,
    key_prefix: str,
    index: int,
    content_type: str,
) -> str:
    return build_loading_photo_object_key(
        key_prefix=key_prefix,
        submitted_at=snapshot.submitted_at,
        service_timezone=service_timezone,
        technician_id=snapshot.technician_id,
        machine_id=snapshot.machine_id,
        batch_id=snapshot.batch_id,
        index=index,
        content_type=content_type,
    )
