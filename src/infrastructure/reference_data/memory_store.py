from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from beartype import beartype

from src.application.reference_data import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    ReferenceDataSyncError,
)
from src.application.reference_data.ports import ReferenceDataSnapshotStore


@beartype
@dataclass(slots=True)
class InMemoryReferenceDataSnapshotStore(ReferenceDataSnapshotStore):
    _snapshots: dict[str, ReferenceDataSnapshot] = field(default_factory=dict)

    @beartype
    def get(self, source_id: ReferenceDataSourceId) -> ReferenceDataSnapshot | None:
        return self._snapshots.get(source_id.value)

    @beartype
    def put(self, snapshot: ReferenceDataSnapshot) -> None:
        self._snapshots[snapshot.source_id.value] = snapshot

    @beartype
    def get_by_id(self, snapshot_id: str) -> ReferenceDataSnapshot | None:
        return self._snapshots.get(snapshot_id)

    @beartype
    def delete_by_id(self, snapshot_id: str) -> None:
        self._snapshots.pop(snapshot_id, None)

    @beartype
    def put_by_id(self, snapshot_id: str, snapshot: ReferenceDataSnapshot) -> None:
        self._snapshots[snapshot_id] = snapshot

    @beartype
    def record_sync_error(
        self,
        source_id: ReferenceDataSourceId,
        message: str,
        at: datetime,
    ) -> None:
        error = ReferenceDataSyncError(message=message, at=at)
        existing = self._snapshots.get(source_id.value)
        if existing is None:
            self._snapshots[source_id.value] = ReferenceDataSnapshot(
                source_id=source_id,
                rows=(),
                content_hash="",
                last_fetched_at=at,
                content_updated_at=at,
                last_sync_error=error,
            )
            return
        self._snapshots[source_id.value] = replace(existing, last_sync_error=error)
