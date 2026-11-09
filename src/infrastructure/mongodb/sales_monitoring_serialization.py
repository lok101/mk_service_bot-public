from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring.control_event import NoSalesIncidentControlRequested
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)

SALES_MONITORING_AGGREGATE_TYPE = "SalesMonitoring"

SalesMonitoringEvent = (
    SalesMonitoringYesterdayNoSales
    | SalesMonitoringYesterdayDecline
    | SalesMonitoringTodayNoSales
    | SalesMonitoringOfflineOpened
    | SalesMonitoringOfflineCleared
    | SalesMonitoringNoSalesStaleOpened
    | SalesMonitoringNoSalesStaleCleared
    | NoSalesIncidentControlRequested
)

_SalesMonitoringSnapshotEvent = (
    SalesMonitoringYesterdayNoSales
    | SalesMonitoringYesterdayDecline
    | SalesMonitoringTodayNoSales
    | SalesMonitoringOfflineOpened
    | SalesMonitoringOfflineCleared
    | SalesMonitoringNoSalesStaleOpened
    | SalesMonitoringNoSalesStaleCleared
)


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def _optional_technician_id(value: TechnicianId | None) -> str | None:
    return value.value if value is not None else None


@beartype
def _optional_technician_from(value: object) -> TechnicianId | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("technician id must be a non-empty string or null")
    return TechnicianId(value)


@beartype
def _optional_datetime_from(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("datetime field must be datetime or null")
    return _as_utc(value)


@beartype
def _optional_str_from(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("string field must be str or null")
    return value


@beartype
def _optional_clear_trigger_from(value: object) -> Literal["sale", "exclude"] | None:
    if value is None:
        return None
    if value == "sale":
        return "sale"
    if value == "exclude":
        return "exclude"
    raise ValueError("clear_trigger must be 'sale', 'exclude', or null")


@beartype
def _optional_bool_from(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("bool field must be bool or null")


@beartype
def _snapshot_payload(event: _SalesMonitoringSnapshotEvent) -> dict[str, Any]:
    return {
        "assigned_technician_id": _optional_technician_id(event.assigned_technician_id),
        "assigned_technician_display": event.assigned_technician_display,
        "last_serviced_by_technician_id": _optional_technician_id(
            event.last_serviced_by_technician_id,
        ),
        "last_serviced_by_display": event.last_serviced_by_display,
        "last_serviced_at": (
            _as_utc(event.last_serviced_at) if event.last_serviced_at is not None else None
        ),
    }


@beartype
def _snapshot_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "assigned_technician_id": _optional_technician_from(payload.get("assigned_technician_id")),
        "assigned_technician_display": _optional_str_from(
            payload.get("assigned_technician_display"),
        ),
        "last_serviced_by_technician_id": _optional_technician_from(
            payload.get("last_serviced_by_technician_id"),
        ),
        "last_serviced_by_display": _optional_str_from(payload.get("last_serviced_by_display")),
        "last_serviced_at": _optional_datetime_from(payload.get("last_serviced_at")),
    }


@beartype
def _payload_for(event: SalesMonitoringEvent) -> dict[str, Any]:
    if isinstance(event, NoSalesIncidentControlRequested):
        return {
            "machine_id": event.machine_id.value,
            "opened_event_id": event.opened_event_id,
            "action": event.action,
            "mute_event_id": event.mute_event_id,
        }
    if isinstance(event, SalesMonitoringYesterdayDecline):
        return {
            "machine_id": event.machine_id.value,
            "report_day": event.report_day.isoformat(),
            "report_sum": format(event.report_sum, "f"),
            "baseline_avg": format(event.baseline_avg, "f"),
            "drop_percent": event.drop_percent,
            **_snapshot_payload(event),
        }
    if isinstance(event, (SalesMonitoringYesterdayNoSales, SalesMonitoringTodayNoSales)):
        return {
            "machine_id": event.machine_id.value,
            "report_day": event.report_day.isoformat(),
            **_snapshot_payload(event),
        }
    if isinstance(event, SalesMonitoringOfflineOpened):
        return {
            "machine_id": event.machine_id.value,
            "opened_at": _as_utc(event.opened_at),
            **_snapshot_payload(event),
        }
    if isinstance(event, SalesMonitoringOfflineCleared):
        return {
            "machine_id": event.machine_id.value,
            "opened_event_id": event.opened_event_id.value,
            "opened_at": _as_utc(event.opened_at),
            "cleared_at": _as_utc(event.cleared_at),
            **_snapshot_payload(event),
        }
    if isinstance(event, SalesMonitoringNoSalesStaleOpened):
        return {
            "machine_id": event.machine_id.value,
            "opened_at": _as_utc(event.opened_at),
            "last_sale_at": (
                _as_utc(event.last_sale_at) if event.last_sale_at is not None else None
            ),
            **_snapshot_payload(event),
        }
    if isinstance(event, SalesMonitoringNoSalesStaleCleared):
        payload: dict[str, Any] = {
            "machine_id": event.machine_id.value,
            "opened_event_id": event.opened_event_id.value,
            "opened_at": _as_utc(event.opened_at),
            "cleared_at": _as_utc(event.cleared_at),
            "last_sale_at": (
                _as_utc(event.last_sale_at) if event.last_sale_at is not None else None
            ),
            **_snapshot_payload(event),
        }
        if event.clear_trigger is not None:
            payload["clear_trigger"] = event.clear_trigger
        if event.bypass_active is not None:
            payload["bypass_active"] = event.bypass_active
        return payload
    raise ValueError(f"Unknown sales monitoring event type: {type(event).__name__}")


@beartype
def sales_monitoring_event_to_document(
    event: SalesMonitoringEvent,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id.value,
        "event_type": type(event).__name__,
        "aggregate_id": event.machine_id.value,
        "aggregate_type": SALES_MONITORING_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": _payload_for(event),
    }


@beartype
def sales_monitoring_event_from_document(document: dict[str, Any]) -> SalesMonitoringEvent:
    event_type = document["event_type"]
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("sales monitoring payload must be a dict")
    event_id = EventId(str(document["event_id"]))
    machine_id = MachineId(str(payload["machine_id"]))
    occurred_at = _as_utc(document["occurred_at"])
    snapshots = _snapshot_kwargs(payload)

    if event_type == NoSalesIncidentControlRequested.__name__:
        action = payload["action"]
        if action not in ("mute", "mute_cancel", "engineer_wait"):
            raise ValueError(f"Unknown no-sales control action: {action!r}")
        return NoSalesIncidentControlRequested(
            event_id=event_id,
            machine_id=machine_id,
            opened_event_id=str(payload["opened_event_id"]),
            action=action,
            mute_event_id=_optional_str_from(payload.get("mute_event_id")),
            occurred_at=occurred_at,
        )
    if event_type == SalesMonitoringYesterdayNoSales.__name__:
        return SalesMonitoringYesterdayNoSales(
            event_id=event_id,
            machine_id=machine_id,
            report_day=date.fromisoformat(str(payload["report_day"])),
            occurred_at=occurred_at,
            **snapshots,
        )
    if event_type == SalesMonitoringYesterdayDecline.__name__:
        return SalesMonitoringYesterdayDecline(
            event_id=event_id,
            machine_id=machine_id,
            report_day=date.fromisoformat(str(payload["report_day"])),
            occurred_at=occurred_at,
            report_sum=Decimal(str(payload["report_sum"])),
            baseline_avg=Decimal(str(payload["baseline_avg"])),
            drop_percent=int(payload["drop_percent"]),
            **snapshots,
        )
    if event_type == SalesMonitoringTodayNoSales.__name__:
        return SalesMonitoringTodayNoSales(
            event_id=event_id,
            machine_id=machine_id,
            report_day=date.fromisoformat(str(payload["report_day"])),
            occurred_at=occurred_at,
            **snapshots,
        )
    if event_type == SalesMonitoringOfflineOpened.__name__:
        return SalesMonitoringOfflineOpened(
            event_id=event_id,
            machine_id=machine_id,
            opened_at=_as_utc(payload["opened_at"]),
            occurred_at=occurred_at,
            **snapshots,
        )
    if event_type == SalesMonitoringOfflineCleared.__name__:
        return SalesMonitoringOfflineCleared(
            event_id=event_id,
            machine_id=machine_id,
            opened_event_id=EventId(str(payload["opened_event_id"])),
            opened_at=_as_utc(payload["opened_at"]),
            cleared_at=_as_utc(payload["cleared_at"]),
            occurred_at=occurred_at,
            **snapshots,
        )
    if event_type == SalesMonitoringNoSalesStaleOpened.__name__:
        return SalesMonitoringNoSalesStaleOpened(
            event_id=event_id,
            machine_id=machine_id,
            opened_at=_as_utc(payload["opened_at"]),
            occurred_at=occurred_at,
            last_sale_at=_optional_datetime_from(payload.get("last_sale_at")),
            **snapshots,
        )
    if event_type == SalesMonitoringNoSalesStaleCleared.__name__:
        return SalesMonitoringNoSalesStaleCleared(
            event_id=event_id,
            machine_id=machine_id,
            opened_event_id=EventId(str(payload["opened_event_id"])),
            opened_at=_as_utc(payload["opened_at"]),
            cleared_at=_as_utc(payload["cleared_at"]),
            occurred_at=occurred_at,
            last_sale_at=_optional_datetime_from(payload.get("last_sale_at")),
            clear_trigger=_optional_clear_trigger_from(payload.get("clear_trigger")),
            bypass_active=_optional_bool_from(payload.get("bypass_active")),
            **snapshots,
        )
    raise ValueError(f"Unknown sales monitoring event type: {event_type}")
