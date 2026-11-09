from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from src.application.photo_batches.ports import BatchContextPhotoStorage
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef, create_pending_snapshot
from src.infrastructure.photo_batches.scoped_storage import scoped_photo_storage
from src.infrastructure.photo_batches.stubs import InMemoryPhotoStorage

_SUBMITTED_AT = datetime(2026, 6, 5, 10, 0, tzinfo=UTC)


class _RecordingBatchContextStorage:
    def __init__(self) -> None:
        self.save_for_batch = AsyncMock(return_value="s3://bucket/key/0.jpg")
        self.get_bytes = AsyncMock(return_value=b"")
        self.delete = AsyncMock(return_value=None)

    async def save(
        self,
        *,
        batch_id: BatchId,
        index: int,
        data: bytes,
        content_type: str,
    ) -> str:
        raise AssertionError("save should not be called when save_for_batch is available")


def _snapshot() -> PhotoBatchSnapshot:
    return create_pending_snapshot(
        batch_id=BatchId("batch-scoped-1"),
        purpose="loading",
        technician_id=TechnicianId("tech-1"),
        machine_id=MachineId("vm-1"),
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id="file-1",
                file_unique_id="unique-1",
                message_id=1,
            ),
        ),
    )


def test_scoped_storage_delegates_to_save_for_batch_on_batch_context_storage() -> None:
    inner = _RecordingBatchContextStorage()
    assert isinstance(inner, BatchContextPhotoStorage)

    storage = scoped_photo_storage(
        inner,
        snapshot=_snapshot(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="prefix",
    )

    storage_key = asyncio.run(
        storage.save(
            batch_id=BatchId("batch-scoped-1"),
            index=0,
            data=b"photo",
            content_type="image/jpeg",
        ),
    )

    assert storage_key == "s3://bucket/key/0.jpg"
    inner.save_for_batch.assert_awaited_once()
    inner.save_for_batch.assert_awaited_with(
        batch_id=BatchId("batch-scoped-1"),
        index=0,
        data=b"photo",
        content_type="image/jpeg",
        technician_id=TechnicianId("tech-1"),
        machine_id=MachineId("vm-1"),
        submitted_at=_SUBMITTED_AT,
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        key_prefix="prefix",
    )


def test_scoped_storage_uses_save_on_in_memory() -> None:
    inner = InMemoryPhotoStorage()
    storage = scoped_photo_storage(
        inner,
        snapshot=_snapshot(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
    )

    storage_key = asyncio.run(
        storage.save(
            batch_id=BatchId("batch-scoped-1"),
            index=0,
            data=b"photo",
            content_type="image/jpeg",
        ),
    )

    assert storage_key == "memory://batch-scoped-1/0"
    assert asyncio.run(storage.get_bytes(storage_key)) == b"photo"
