from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId, TechnicianId
from src.domain.technician_settlement.portion_events import (
    SettlementPortionEvent,
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)

SETTLEMENT_PORTION_AGGREGATE_TYPE = "SettlementPortion"

_PORTION_EVENT_TYPES: dict[str, type[SettlementPortionEvent]] = {
    SettlementPortionSyncTransfersRequested.__name__: SettlementPortionSyncTransfersRequested,
    SettlementPortionSalesVerifyRequested.__name__: SettlementPortionSalesVerifyRequested,
    SettlementPortionReconcileRequested.__name__: SettlementPortionReconcileRequested,
}


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def settlement_portion_event_to_document(
    event: SettlementPortionEvent,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "technician_id": event.technician_id.value,
        "warehouse_inventory_id": event.warehouse_inventory_id,
        "warehouse_inventory_moment": _as_utc(event.warehouse_inventory_moment),
    }
    if isinstance(event, SettlementPortionReconcileRequested) and event.not_before is not None:
        payload["not_before"] = _as_utc(event.not_before)
    return {
        "event_id": event.event_id.value,
        "event_type": type(event).__name__,
        "aggregate_id": event.technician_id.value,
        "aggregate_type": SETTLEMENT_PORTION_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": payload,
    }


@beartype
def settlement_portion_event_from_document(document: dict[str, Any]) -> SettlementPortionEvent:
    event_type = document["event_type"]
    event_cls = _PORTION_EVENT_TYPES.get(str(event_type))
    if event_cls is None:
        raise ValueError(f"Unknown settlement portion event type: {event_type}")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("settlement portion payload must be a dict")
    event_id = EventId(str(document["event_id"]))
    technician_id = TechnicianId(str(payload["technician_id"]))
    warehouse_inventory_id = str(payload["warehouse_inventory_id"])
    warehouse_inventory_moment = _as_utc(payload["warehouse_inventory_moment"])
    occurred_at = _as_utc(document["occurred_at"])
    if event_cls is SettlementPortionReconcileRequested:
        not_before_raw = payload.get("not_before")
        return SettlementPortionReconcileRequested(
            event_id=event_id,
            technician_id=technician_id,
            warehouse_inventory_id=warehouse_inventory_id,
            warehouse_inventory_moment=warehouse_inventory_moment,
            occurred_at=occurred_at,
            not_before=_as_utc(not_before_raw) if not_before_raw is not None else None,
        )
    return event_cls(
        event_id=event_id,
        technician_id=technician_id,
        warehouse_inventory_id=warehouse_inventory_id,
        warehouse_inventory_moment=warehouse_inventory_moment,
        occurred_at=occurred_at,
    )
