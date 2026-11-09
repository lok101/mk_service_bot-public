from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from beartype import beartype

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.photo_batch import (
    PhotoBatchSnapshot,
    PhotoPurpose,
    PhotoRef,
    StoredPhotoRef,
    accept_snapshot,
    attach_proxy_message_ids,
    attach_stored_files,
    create_pending_snapshot,
    reject_snapshot,
)


@beartype
@dataclass
class InMemoryPhotoBatchStore:
    _by_batch_id: dict[str, PhotoBatchSnapshot] = field(default_factory=dict)
    _by_event_id: dict[str, str] = field(default_factory=dict)

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
    ) -> PhotoBatchSnapshot:
        existing = self._by_batch_id.get(batch_id.value)
        if existing is not None:
            if existing.status == "accepted":
                return existing
            # pending: last-write-wins refresh of the in-flight payload; rejected: reactivate.
            if existing.status in {"pending", "rejected"}:
                snapshot = create_pending_snapshot(
                    batch_id=batch_id,
                    purpose=purpose,
                    technician_id=technician_id,
                    machine_id=machine_id,
                    submitted_at=submitted_at,
                    photos=photos,
                )
                self._by_batch_id[batch_id.value] = snapshot
                return snapshot

        snapshot = create_pending_snapshot(
            batch_id=batch_id,
            purpose=purpose,
            technician_id=technician_id,
            machine_id=machine_id,
            submitted_at=submitted_at,
            photos=photos,
        )
        self._by_batch_id[batch_id.value] = snapshot
        return snapshot

    @beartype
    def mark_accepted(
        self,
        batch_id: BatchId,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = accept_snapshot(
            snapshot,
            event_id=event_id,
            occurred_at=occurred_at,
        )
        self._by_batch_id[batch_id.value] = updated
        self._by_event_id[event_id] = batch_id.value
        return updated

    @beartype
    def mark_rejected(
        self,
        batch_id: BatchId,
        *,
        reason: str,
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = reject_snapshot(snapshot, reason=reason)
        self._by_batch_id[batch_id.value] = updated
        return updated

    @beartype
    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None:
        return self._by_batch_id.get(batch_id.value)

    @beartype
    def get_by_event_id(self, event_id: str) -> PhotoBatchSnapshot | None:
        batch_key = self._by_event_id.get(event_id)
        if batch_key is None:
            return None
        return self._by_batch_id.get(batch_key)

    @beartype
    def update_stored_files(
        self,
        batch_id: BatchId,
        stored_files: tuple[StoredPhotoRef, ...],
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = attach_stored_files(snapshot, stored_files)
        self._by_batch_id[batch_id.value] = updated
        return updated

    @beartype
    def update_proxy_message_ids(
        self,
        batch_id: BatchId,
        message_ids: tuple[int, ...],
    ) -> PhotoBatchSnapshot:
        snapshot = self._require_snapshot(batch_id)
        updated = attach_proxy_message_ids(snapshot, message_ids)
        self._by_batch_id[batch_id.value] = updated
        return updated

    @beartype
    def _require_snapshot(self, batch_id: BatchId) -> PhotoBatchSnapshot:
        snapshot = self._by_batch_id.get(batch_id.value)
        if snapshot is None:
            raise ValueError(f"Photo batch {batch_id.value!r} was not found")
        return snapshot
