from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import (
    PhotoBatchSnapshot,
    PhotoRef,
    StoredPhotoRef,
    accept_snapshot,
    attach_proxy_message_ids,
    attach_stored_files,
    create_pending_snapshot,
    reject_snapshot,
)

_BATCH_ID = BatchId("batch-01")
_TECH = TechnicianId("tech-a")
_MACHINE = MachineId("vm-01")
_SUBMITTED_AT = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
_PHOTO = PhotoRef(
    file_id="file-1",
    file_unique_id="unique-1",
    message_id=100,
)


def test_create_pending_snapshot() -> None:
    snapshot = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    assert snapshot.status == "pending"
    assert snapshot.event_id is None


def test_accept_snapshot() -> None:
    pending = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    occurred_at = datetime(2026, 5, 15, 12, 1, tzinfo=UTC)
    accepted = accept_snapshot(
        pending,
        event_id="event-1",
        occurred_at=occurred_at,
    )
    assert accepted.status == "accepted"
    assert accepted.event_id == "event-1"
    assert accepted.occurred_at == occurred_at


def test_reject_snapshot() -> None:
    pending = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    rejected = reject_snapshot(pending, reason="download failed")
    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "download failed"


def test_attach_stored_files() -> None:
    pending = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    accepted = accept_snapshot(
        pending,
        event_id="event-1",
        occurred_at=datetime(2026, 5, 15, 12, 1, tzinfo=UTC),
    )
    stored = (
        StoredPhotoRef(
            index=0,
            storage_key="s3/key-0",
            content_type="image/jpeg",
            size_bytes=1024,
            content_hash="a" * 64,
        ),
    )
    updated = attach_stored_files(accepted, stored)
    assert updated.stored_files == stored


def test_pending_snapshot_rejects_event_id() -> None:
    with pytest.raises(ValueError, match="pending batch must not have event_id"):
        PhotoBatchSnapshot(
            batch_id=_BATCH_ID,
            purpose="loading",
            technician_id=_TECH,
            machine_id=_MACHINE,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO,),
            status="pending",
            event_id="event-1",
        )


def test_attach_proxy_message_ids_on_accepted_batch() -> None:
    pending = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    accepted = accept_snapshot(
        pending,
        event_id="event-1",
        occurred_at=datetime(2026, 5, 15, 12, 1, tzinfo=UTC),
    )
    updated = attach_proxy_message_ids(accepted, (10, 11))
    assert updated.proxy_message_ids == (10, 11)


def test_attach_proxy_message_ids_rejects_pending_batch() -> None:
    pending = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    with pytest.raises(ValueError, match="only accepted batch"):
        attach_proxy_message_ids(pending, (10,))


def test_accept_snapshot_requires_pending() -> None:
    pending = create_pending_snapshot(
        batch_id=_BATCH_ID,
        purpose="loading",
        technician_id=_TECH,
        machine_id=_MACHINE,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO,),
    )
    accepted = accept_snapshot(
        pending,
        event_id="event-1",
        occurred_at=datetime(2026, 5, 15, 12, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="only pending batch can be accepted"):
        accept_snapshot(
            accepted,
            event_id="event-2",
            occurred_at=datetime(2026, 5, 15, 12, 2, tzinfo=UTC),
        )
