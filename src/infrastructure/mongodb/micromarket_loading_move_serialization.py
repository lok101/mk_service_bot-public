from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested

MICROMARKET_LOADING_MOVE_AGGREGATE_TYPE = "MicromarketLoadingMove"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def micromarket_loading_move_event_to_document(
    event: MicromarketLoadingMoveCommandRequested,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id.value,
        "event_type": MicromarketLoadingMoveCommandRequested.__name__,
        "aggregate_id": event.command_id,
        "aggregate_type": MICROMARKET_LOADING_MOVE_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": {"command_id": event.command_id},
    }


@beartype
def micromarket_loading_move_event_from_document(
    document: dict[str, Any],
) -> MicromarketLoadingMoveCommandRequested:
    event_type = document["event_type"]
    if event_type != MicromarketLoadingMoveCommandRequested.__name__:
        raise ValueError(f"Unknown micromarket loading move event type: {event_type}")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("micromarket loading move payload must be a dict")
    command_id = payload["command_id"]
    if not isinstance(command_id, str):
        raise ValueError("command_id must be str")
    occurred_at = document["occurred_at"]
    if not isinstance(occurred_at, datetime):
        raise ValueError("occurred_at must be datetime")
    return MicromarketLoadingMoveCommandRequested(
        event_id=EventId(document["event_id"]),
        command_id=command_id,
        occurred_at=occurred_at,
    )
