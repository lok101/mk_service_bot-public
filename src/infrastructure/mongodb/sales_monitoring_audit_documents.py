from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)

SalesFindingEvent = (
    SalesMonitoringYesterdayNoSales | SalesMonitoringYesterdayDecline | SalesMonitoringTodayNoSales
)


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def sales_audit_document_id(
    *,
    event_type: str,
    machine_id: MachineId,
    report_day: date,
) -> str:
    return f"{event_type}:{machine_id.value}:{report_day.isoformat()}"


@beartype
def offline_audit_document_id(machine_id: MachineId) -> str:
    return f"offline:{machine_id.value}"


@beartype
def no_sales_audit_document_id(machine_id: MachineId) -> str:
    return f"no_sales:{machine_id.value}"


@beartype
def no_sales_episode_document_id(machine_id: MachineId, opened_event_id: EventId | str) -> str:
    opened = opened_event_id.value if isinstance(opened_event_id, EventId) else opened_event_id
    return f"no_sales_episode:{machine_id.value}:{opened}"


@beartype
def _optional_technician_id(value: TechnicianId | None) -> str | None:
    return value.value if value is not None else None


@beartype
def _snapshot_fields(event: DomainEvent) -> dict[str, Any]:
    last_serviced_at = getattr(event, "last_serviced_at", None)
    return {
        "assigned_technician_id": _optional_technician_id(
            getattr(event, "assigned_technician_id", None),
        ),
        "assigned_technician_display": getattr(event, "assigned_technician_display", None),
        "last_serviced_by_technician_id": _optional_technician_id(
            getattr(event, "last_serviced_by_technician_id", None),
        ),
        "last_serviced_by_display": getattr(event, "last_serviced_by_display", None),
        "last_serviced_at": (
            _as_utc(last_serviced_at) if isinstance(last_serviced_at, datetime) else None
        ),
    }


@beartype
def document_from_sales_finding(event: SalesFindingEvent) -> dict[str, Any]:
    event_type = type(event).__name__
    document: dict[str, Any] = {
        "_id": sales_audit_document_id(
            event_type=event_type,
            machine_id=event.machine_id,
            report_day=event.report_day,
        ),
        "kind": "sales",
        "event_type": event_type,
        "event_id": event.event_id.value,
        "machine_id": event.machine_id.value,
        "report_day": event.report_day.isoformat(),
        "occurred_at": _as_utc(event.occurred_at),
        **_snapshot_fields(event),
    }
    if isinstance(event, SalesMonitoringYesterdayDecline):
        document["report_sum"] = format(event.report_sum, "f")
        document["baseline_avg"] = format(event.baseline_avg, "f")
        document["drop_percent"] = event.drop_percent
    return document


@beartype
def document_from_offline_opened(event: SalesMonitoringOfflineOpened) -> dict[str, Any]:
    return {
        "_id": offline_audit_document_id(event.machine_id),
        "kind": "offline",
        "event_type": type(event).__name__,
        "event_id": event.event_id.value,
        "machine_id": event.machine_id.value,
        "status": "open",
        "opened_at": _as_utc(event.opened_at),
        "cleared_at": None,
        "occurred_at": _as_utc(event.occurred_at),
        **_snapshot_fields(event),
    }


@beartype
def apply_offline_cleared(
    existing: dict[str, Any] | None,
    event: SalesMonitoringOfflineCleared,
) -> dict[str, Any]:
    base = (
        dict(existing)
        if existing is not None
        else {
            "_id": offline_audit_document_id(event.machine_id),
            "kind": "offline",
            "machine_id": event.machine_id.value,
            "opened_at": _as_utc(event.opened_at),
        }
    )
    opened_at_raw = (
        existing["opened_at"] if existing and "opened_at" in existing else event.opened_at
    )
    opened_at = (
        _as_utc(opened_at_raw) if isinstance(opened_at_raw, datetime) else _as_utc(event.opened_at)
    )
    base.update(
        {
            "event_type": type(event).__name__,
            "event_id": event.event_id.value,
            "opened_event_id": event.opened_event_id.value,
            "status": "cleared",
            "opened_at": opened_at,
            "cleared_at": _as_utc(event.cleared_at),
            "occurred_at": _as_utc(event.occurred_at),
            **_snapshot_fields(event),
        }
    )
    return base


@beartype
def document_from_no_sales_stale_opened(
    event: SalesMonitoringNoSalesStaleOpened,
) -> dict[str, Any]:
    return {
        "_id": no_sales_audit_document_id(event.machine_id),
        "kind": "no_sales",
        "event_type": type(event).__name__,
        "event_id": event.event_id.value,
        "opened_event_id": event.event_id.value,
        "machine_id": event.machine_id.value,
        "status": "open",
        "opened_at": _as_utc(event.opened_at),
        "cleared_at": None,
        "occurred_at": _as_utc(event.occurred_at),
        "last_sale_at": (_as_utc(event.last_sale_at) if event.last_sale_at is not None else None),
        **_snapshot_fields(event),
    }


@beartype
def apply_no_sales_stale_cleared(
    existing: dict[str, Any] | None,
    event: SalesMonitoringNoSalesStaleCleared,
) -> dict[str, Any]:
    base = (
        dict(existing)
        if existing is not None
        else {
            "_id": no_sales_audit_document_id(event.machine_id),
            "kind": "no_sales",
            "machine_id": event.machine_id.value,
            "opened_at": _as_utc(event.opened_at),
        }
    )
    opened_at_raw = (
        existing["opened_at"] if existing and "opened_at" in existing else event.opened_at
    )
    opened_at = (
        _as_utc(opened_at_raw) if isinstance(opened_at_raw, datetime) else _as_utc(event.opened_at)
    )
    last_sale_at = _as_utc(event.last_sale_at) if event.last_sale_at is not None else None
    base.update(
        {
            "event_type": type(event).__name__,
            "event_id": event.event_id.value,
            "opened_event_id": event.opened_event_id.value,
            "status": "cleared",
            "opened_at": opened_at,
            "cleared_at": _as_utc(event.cleared_at),
            "occurred_at": _as_utc(event.occurred_at),
            "last_sale_at": last_sale_at,
            **_snapshot_fields(event),
        }
    )
    return base


@beartype
def document_from_no_sales_episode_opened(
    event: SalesMonitoringNoSalesStaleOpened,
) -> dict[str, Any]:
    return {
        "_id": no_sales_episode_document_id(event.machine_id, event.event_id),
        "kind": "no_sales_episode",
        "machine_id": event.machine_id.value,
        "opened_event_id": event.event_id.value,
        "opened_at": _as_utc(event.opened_at),
        "cleared_at": None,
        "last_sale_at": (_as_utc(event.last_sale_at) if event.last_sale_at is not None else None),
        "clear_trigger": None,
        "bypass_active": None,
        "assigned_technician_id": _optional_technician_id(event.assigned_technician_id),
        "assigned_technician_display": event.assigned_technician_display,
    }


@beartype
def document_from_no_sales_episode(event: SalesMonitoringNoSalesStaleCleared) -> dict[str, Any]:
    if event.clear_trigger is not None:
        bypass: bool | None = False if event.bypass_active is None else event.bypass_active
    else:
        bypass = event.bypass_active  # может остаться None
    return {
        "_id": no_sales_episode_document_id(event.machine_id, event.opened_event_id),
        "kind": "no_sales_episode",
        "machine_id": event.machine_id.value,
        "opened_event_id": event.opened_event_id.value,
        "opened_at": _as_utc(event.opened_at),
        "cleared_at": _as_utc(event.cleared_at),
        "last_sale_at": (_as_utc(event.last_sale_at) if event.last_sale_at is not None else None),
        "clear_trigger": event.clear_trigger,
        "bypass_active": bypass,
        "assigned_technician_id": _optional_technician_id(event.assigned_technician_id),
        "assigned_technician_display": event.assigned_technician_display,
    }


@beartype
def build_audit_document(
    event: DomainEvent,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(
        event,
        (
            SalesMonitoringYesterdayNoSales,
            SalesMonitoringYesterdayDecline,
            SalesMonitoringTodayNoSales,
        ),
    ):
        return document_from_sales_finding(event)
    if isinstance(event, SalesMonitoringOfflineOpened):
        return document_from_offline_opened(event)
    if isinstance(event, SalesMonitoringOfflineCleared):
        return apply_offline_cleared(existing, event)
    if isinstance(event, SalesMonitoringNoSalesStaleOpened):
        return document_from_no_sales_stale_opened(event)
    if isinstance(event, SalesMonitoringNoSalesStaleCleared):
        return apply_no_sales_stale_cleared(existing, event)
    raise TypeError(f"Unsupported sales monitoring audit event: {type(event).__name__}")


@beartype
def normalize_audit_document(document: dict[str, Any]) -> dict[str, object]:
    """Restore UTC tzinfo that mongomock/BSON may strip from datetime fields."""
    result: dict[str, object] = dict(document)
    for key in ("opened_at", "cleared_at", "occurred_at", "last_serviced_at", "last_sale_at"):
        value = result.get(key)
        if isinstance(value, datetime):
            result[key] = _as_utc(value)
    return result
