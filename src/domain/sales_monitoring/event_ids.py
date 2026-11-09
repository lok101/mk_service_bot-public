from __future__ import annotations

from datetime import date, datetime

from beartype import beartype

from src.domain.ids import EventId, MachineId


@beartype
def sales_finding_event_id(
    *,
    event_type: str,
    machine_id: MachineId,
    report_day: date,
) -> EventId:
    return EventId(f"{event_type}:{machine_id.value}:{report_day.isoformat()}")


@beartype
def offline_opened_event_id(
    *,
    machine_id: MachineId,
    opened_at: datetime,
) -> EventId:
    return EventId(f"sales-monitoring-offline-opened:{machine_id.value}:{opened_at.isoformat()}")


@beartype
def offline_cleared_event_id(
    *,
    machine_id: MachineId,
    cleared_at: datetime,
) -> EventId:
    return EventId(f"sales-monitoring-offline-cleared:{machine_id.value}:{cleared_at.isoformat()}")


@beartype
def no_sales_stale_opened_event_id(
    *,
    machine_id: MachineId,
    opened_at: datetime,
) -> EventId:
    return EventId(
        f"sales-monitoring-no-sales-stale-opened:{machine_id.value}:{opened_at.isoformat()}"
    )


@beartype
def no_sales_stale_cleared_event_id(
    *,
    machine_id: MachineId,
    cleared_at: datetime,
) -> EventId:
    return EventId(
        f"sales-monitoring-no-sales-stale-cleared:{machine_id.value}:{cleared_at.isoformat()}"
    )
