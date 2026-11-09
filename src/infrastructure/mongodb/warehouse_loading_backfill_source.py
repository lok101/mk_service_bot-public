from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING

from src.application.technician_warehouse.ports import (
    LoadingSubmittedRef,
    WarehouseLoadingBackfillSource,
)
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.contracts import MACHINE_OPERATIONS_AGGREGATE_TYPE
from src.infrastructure.mongodb.technician_warehouse_serialization import (
    TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
)

_LOADING_SUBMITTED = "LoadingSubmitted"
_LOADING_OBSERVED = "TechnicianWarehouseLoadingObserved"


@runtime_checkable
class _EventsCollection(Protocol):
    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]],
    ) -> Any: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
@dataclass(frozen=True, slots=True)
class MongoWarehouseLoadingBackfillSource(WarehouseLoadingBackfillSource):
    machine_events: _EventsCollection
    warehouse_events: _EventsCollection

    @beartype
    def list_loading_submitted(
        self,
        *,
        technician_id: TechnicianId | None,
    ) -> tuple[LoadingSubmittedRef, ...]:
        query: dict[str, Any] = {
            "event_type": _LOADING_SUBMITTED,
            "aggregate_type": MACHINE_OPERATIONS_AGGREGATE_TYPE,
        }
        if technician_id is not None:
            query["payload.technician_id"] = technician_id.value
        cursor = self.machine_events.find(
            query,
            sort=[("payload.submitted_at", ASCENDING)],
        )
        refs: list[LoadingSubmittedRef] = []
        for document in cursor:
            payload = document["payload"]
            refs.append(
                LoadingSubmittedRef(
                    event_id=document["event_id"],
                    technician_id=TechnicianId(payload["technician_id"]),
                    machine_id=MachineId(payload["machine_id"]),
                    submitted_at=_as_utc(payload["submitted_at"]),
                )
            )
        return tuple(refs)

    @beartype
    def list_observed_source_event_ids(
        self,
        *,
        technician_id: TechnicianId | None,
    ) -> frozenset[str]:
        query: dict[str, Any] = {
            "event_type": _LOADING_OBSERVED,
            "aggregate_type": TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
        }
        if technician_id is not None:
            query["aggregate_id"] = technician_id.value
        cursor = self.warehouse_events.find(
            query,
            sort=[("aggregate_version", ASCENDING)],
        )
        return frozenset(document["payload"]["source_event_id"] for document in cursor)
