from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId
from src.domain.technician_last_maintenance import (
    TechnicianLastMaintenanceSnapshot,
    should_upsert_last_maintenance,
)


@runtime_checkable
class TechnicianLastMaintenanceCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@beartype
def snapshot_to_document(snapshot: TechnicianLastMaintenanceSnapshot) -> dict[str, Any]:
    return {
        "_id": snapshot.technician_id.value,
        "machine_id": snapshot.machine_id.value,
        "completed_at": snapshot.completed_at,
    }


@beartype
def snapshot_from_document(document: dict[str, Any]) -> TechnicianLastMaintenanceSnapshot:
    return TechnicianLastMaintenanceSnapshot(
        technician_id=TechnicianId(document["_id"]),
        machine_id=MachineId(document["machine_id"]),
        completed_at=_ensure_aware(document["completed_at"]),
    )


@beartype
@dataclass(slots=True)
class MongoTechnicianLastMaintenanceProjection:
    _collection: TechnicianLastMaintenanceCollection

    @beartype
    def get_last(self, technician_id: TechnicianId) -> TechnicianLastMaintenanceSnapshot | None:
        document = self._collection.find_one({"_id": technician_id.value})
        if document is None:
            return None
        return snapshot_from_document(document)

    @beartype
    def upsert(self, snapshot: TechnicianLastMaintenanceSnapshot) -> None:
        existing = self.get_last(snapshot.technician_id)
        if not should_upsert_last_maintenance(snapshot, existing):
            return
        self._collection.replace_one(
            {"_id": snapshot.technician_id.value},
            snapshot_to_document(snapshot),
            upsert=True,
        )
