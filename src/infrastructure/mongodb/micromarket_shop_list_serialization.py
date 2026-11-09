from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested

MICROMARKET_SHOP_LIST_AGGREGATE_TYPE = "MicromarketShopList"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def micromarket_shop_list_event_to_document(
    event: MicromarketShopListPublishRequested,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id.value,
        "event_type": MicromarketShopListPublishRequested.__name__,
        "aggregate_id": event.machine_code,
        "aggregate_type": MICROMARKET_SHOP_LIST_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": {
            "machine_code": event.machine_code,
            "publication_id": event.publication_id,
            "lines": [list(line) for line in event.lines],
        },
    }


@beartype
def micromarket_shop_list_event_from_document(
    document: dict[str, Any],
) -> MicromarketShopListPublishRequested:
    event_type = document["event_type"]
    if event_type != MicromarketShopListPublishRequested.__name__:
        raise ValueError(f"Unknown micromarket shop list event type: {event_type}")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("micromarket shop list payload must be a dict")
    lines_raw = payload["lines"]
    if not isinstance(lines_raw, list):
        raise ValueError("lines must be a list")
    lines: list[tuple[str, str, int, bool]] = []
    for item in lines_raw:
        if not isinstance(item, (list, tuple)) or len(item) not in (3, 4):
            raise ValueError("line must be a 3- or 4-tuple")
        product_code, price_rub, kit_group_id = item[0], item[1], item[2]
        disabled = bool(item[3]) if len(item) == 4 else False
        lines.append((str(product_code), str(price_rub), int(kit_group_id), disabled))
    return MicromarketShopListPublishRequested(
        event_id=EventId(str(document["event_id"])),
        machine_code=str(payload["machine_code"]),
        publication_id=str(payload["publication_id"]),
        lines=tuple(lines),
        occurred_at=_as_utc(document["occurred_at"]),
    )
