from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.machine_pnl.events import MachineMonthPnlRequested, MachinePeriodPnlRequested

MACHINE_PNL_AGGREGATE_TYPE = "MachinePnl"

MachinePnlOutboxEvent = MachinePeriodPnlRequested | MachineMonthPnlRequested


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def machine_pnl_event_to_document(
    event: MachinePnlOutboxEvent,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    if isinstance(event, MachineMonthPnlRequested):
        return {
            "event_id": event.event_id.value,
            "event_type": MachineMonthPnlRequested.__name__,
            "aggregate_id": event.source_period_id,
            "aggregate_type": MACHINE_PNL_AGGREGATE_TYPE,
            "aggregate_version": aggregate_version,
            "occurred_at": _as_utc(event.occurred_at),
            "payload": {
                "machine_id": event.machine_id,
                "period_start_dates": [d.isoformat() for d in event.period_start_dates],
                "source_period_id": event.source_period_id,
            },
        }
    return {
        "event_id": event.event_id.value,
        "event_type": MachinePeriodPnlRequested.__name__,
        "aggregate_id": event.period_id,
        "aggregate_type": MACHINE_PNL_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": {
            "period_id": event.period_id,
            "source_session_id": event.source_session_id,
        },
    }


@beartype
def machine_pnl_event_from_document(document: dict[str, Any]) -> MachinePnlOutboxEvent:
    event_type = document["event_type"]
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("machine pnl payload must be a dict")
    if event_type == MachineMonthPnlRequested.__name__:
        raw_dates = payload["period_start_dates"]
        if not isinstance(raw_dates, list | tuple):
            raise ValueError("period_start_dates must be a list")
        period_start_dates = tuple(date.fromisoformat(str(item)) for item in raw_dates)
        return MachineMonthPnlRequested(
            event_id=EventId(str(document["event_id"])),
            machine_id=str(payload["machine_id"]),
            period_start_dates=period_start_dates,
            source_period_id=str(payload["source_period_id"]),
            occurred_at=_as_utc(document["occurred_at"]),
        )
    if event_type != MachinePeriodPnlRequested.__name__:
        raise ValueError(f"Unknown machine pnl event type: {event_type}")
    period_id = str(payload["period_id"])
    source_session_id = str(payload["source_session_id"])
    return MachinePeriodPnlRequested(
        event_id=EventId(str(document["event_id"])),
        period_id=period_id,
        source_session_id=source_session_id,
        occurred_at=_as_utc(document["occurred_at"]),
    )
