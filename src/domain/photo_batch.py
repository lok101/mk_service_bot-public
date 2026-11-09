from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from beartype import beartype

from src.domain.ids import BatchId, MachineId, TechnicianId

PhotoPurpose = Literal["loading"]
PhotoBatchStatus = Literal["pending", "accepted", "rejected"]


@beartype
@dataclass(frozen=True, slots=True)
class PhotoRef:
    file_id: str
    file_unique_id: str
    message_id: int
    media_group_id: str | None = None

    def __post_init__(self) -> None:
        if not self.file_id:
            raise ValueError("file_id must not be empty")
        if not self.file_unique_id:
            raise ValueError("file_unique_id must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class StoredPhotoRef:
    index: int
    storage_key: str
    content_type: str
    size_bytes: int
    content_hash: str = ""

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be non-negative")
        if not self.storage_key:
            raise ValueError("storage_key must not be empty")
        if not self.content_type:
            raise ValueError("content_type must not be empty")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")


@beartype
@dataclass(frozen=True, slots=True)
class PhotoBatchSnapshot:
    batch_id: BatchId
    purpose: PhotoPurpose
    technician_id: TechnicianId
    machine_id: MachineId
    submitted_at: datetime
    photos: tuple[PhotoRef, ...]
    status: PhotoBatchStatus
    event_id: str | None = None
    occurred_at: datetime | None = None
    stored_files: tuple[StoredPhotoRef, ...] = ()
    proxy_message_ids: tuple[int, ...] = ()
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.photos:
            raise ValueError("photos must not be empty")
        if self.status == "pending":
            if self.event_id is not None:
                raise ValueError("pending batch must not have event_id")
            if self.occurred_at is not None:
                raise ValueError("pending batch must not have occurred_at")
            if self.rejection_reason is not None:
                raise ValueError("pending batch must not have rejection_reason")
        if self.status == "accepted":
            if not self.event_id:
                raise ValueError("accepted batch must have event_id")
            if self.occurred_at is None:
                raise ValueError("accepted batch must have occurred_at")
            if self.rejection_reason is not None:
                raise ValueError("accepted batch must not have rejection_reason")
        if self.status == "rejected":
            if not self.rejection_reason:
                raise ValueError("rejected batch must have rejection_reason")
            if self.event_id is not None:
                raise ValueError("rejected batch must not have event_id")


@beartype
def create_pending_snapshot(
    *,
    batch_id: BatchId,
    purpose: PhotoPurpose,
    technician_id: TechnicianId,
    machine_id: MachineId,
    submitted_at: datetime,
    photos: tuple[PhotoRef, ...],
) -> PhotoBatchSnapshot:
    return PhotoBatchSnapshot(
        batch_id=batch_id,
        purpose=purpose,
        technician_id=technician_id,
        machine_id=machine_id,
        submitted_at=submitted_at,
        photos=photos,
        status="pending",
    )


@beartype
def accept_snapshot(
    snapshot: PhotoBatchSnapshot,
    *,
    event_id: str,
    occurred_at: datetime,
) -> PhotoBatchSnapshot:
    if snapshot.status != "pending":
        raise ValueError("only pending batch can be accepted")
    if not event_id:
        raise ValueError("event_id must not be empty")
    return replace(
        snapshot,
        status="accepted",
        event_id=event_id,
        occurred_at=occurred_at,
    )


@beartype
def reject_snapshot(
    snapshot: PhotoBatchSnapshot,
    *,
    reason: str,
) -> PhotoBatchSnapshot:
    if snapshot.status != "pending":
        raise ValueError("only pending batch can be rejected")
    if not reason.strip():
        raise ValueError("rejection reason must not be empty")
    return replace(
        snapshot,
        status="rejected",
        rejection_reason=reason,
    )


@beartype
def attach_stored_files(
    snapshot: PhotoBatchSnapshot,
    stored_files: tuple[StoredPhotoRef, ...],
) -> PhotoBatchSnapshot:
    if snapshot.status != "accepted":
        raise ValueError("only accepted batch can have stored files attached")
    for item in stored_files:
        if not item.content_hash:
            raise ValueError("stored file content_hash must not be empty")
    return replace(snapshot, stored_files=stored_files)


@beartype
def attach_proxy_message_ids(
    snapshot: PhotoBatchSnapshot,
    message_ids: tuple[int, ...],
) -> PhotoBatchSnapshot:
    if snapshot.status != "accepted":
        raise ValueError("only accepted batch can have proxy messages")
    if not message_ids:
        raise ValueError("proxy message_ids must not be empty")
    return replace(snapshot, proxy_message_ids=message_ids)
