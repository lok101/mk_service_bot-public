from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)

MICROMARKET_POST_VISIT_SQUEEZE_AGGREGATE_TYPE = "MicromarketPostVisitSqueeze"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def micromarket_post_visit_squeeze_event_to_document(
    event: MicromarketPostVisitSqueezeRequested,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id.value,
        "event_type": MicromarketPostVisitSqueezeRequested.__name__,
        "aggregate_id": event.machine_code,
        "aggregate_type": MICROMARKET_POST_VISIT_SQUEEZE_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": {
            "machine_code": event.machine_code,
            "inventory_id": event.inventory_id,
        },
    }


@beartype
def micromarket_post_visit_squeeze_event_from_document(
    document: dict[str, Any],
) -> MicromarketPostVisitSqueezeRequested:
    event_type = document["event_type"]
    if event_type != MicromarketPostVisitSqueezeRequested.__name__:
        raise ValueError(f"Unknown micromarket post visit squeeze event type: {event_type}")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("micromarket post visit squeeze payload must be a dict")
    machine_code = payload["machine_code"]
    inventory_id = payload["inventory_id"]
    if not isinstance(machine_code, str) or not isinstance(inventory_id, str):
        raise ValueError("machine_code and inventory_id must be str")
    occurred_at = document["occurred_at"]
    if not isinstance(occurred_at, datetime):
        raise ValueError("occurred_at must be datetime")
    return MicromarketPostVisitSqueezeRequested(
        event_id=EventId(str(document["event_id"])),
        machine_code=machine_code,
        inventory_id=inventory_id,
        occurred_at=_as_utc(occurred_at),
    )
