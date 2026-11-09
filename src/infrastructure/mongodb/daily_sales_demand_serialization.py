from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested

DAILY_SALES_DEMAND_AGGREGATE_TYPE = "DailySalesDemand"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def daily_sales_demand_event_to_document(
    event: DailySalesDemandRequested,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id.value,
        "event_type": DailySalesDemandRequested.__name__,
        "aggregate_id": event.sales_day.isoformat(),
        "aggregate_type": DAILY_SALES_DEMAND_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": {"sales_day": event.sales_day.isoformat()},
    }


@beartype
def daily_sales_demand_event_from_document(
    document: dict[str, Any],
) -> DailySalesDemandRequested:
    event_type = document["event_type"]
    if event_type != DailySalesDemandRequested.__name__:
        raise ValueError(f"Unknown daily sales demand event type: {event_type}")
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("daily sales demand payload must be a dict")
    sales_day = date.fromisoformat(str(payload["sales_day"]))
    return DailySalesDemandRequested(
        event_id=EventId(str(document["event_id"])),
        sales_day=sales_day,
        occurred_at=_as_utc(document["occurred_at"]),
    )
