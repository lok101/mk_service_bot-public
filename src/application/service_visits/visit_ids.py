from __future__ import annotations

from datetime import date

from beartype import beartype

from src.domain.ids import EventId, MachineId


@beartype
def scheduled_visit_id(machine_id: MachineId, due_date: date) -> str:
    return f"scheduled:{machine_id.value}:{due_date.isoformat()}"


@beartype
def offline_incident_visit_id(opened_event_id: EventId) -> str:
    return f"incident:offline:{opened_event_id.value}"


@beartype
def no_sales_incident_visit_id(machine_id: MachineId) -> str:
    return f"incident:no_sales:{machine_id.value}"


@beartype
def is_day_based_no_sales_visit_id(visit_id: str) -> bool:
    # incident:no_sales:{machine}:{YYYY-MM-DD} — 4 segments after split by ":"
    parts = visit_id.split(":")
    return (
        len(parts) == 4
        and parts[0] == "incident"
        and parts[1] == "no_sales"
        and len(parts[3]) == 10
    )


@beartype
def ad_hoc_visit_id(
    machine_id: MachineId,
    ops_day: date,
    maintenance_event_id: EventId,
) -> str:
    return f"ad_hoc:{machine_id.value}:{ops_day.isoformat()}:{maintenance_event_id.value}"


@beartype
def field_visit_id(machine_id: MachineId, ops_day: date) -> str:
    """Legacy lazy-session id; new ensure-open uses scheduled_visit_id instead."""
    return f"field:{machine_id.value}:{ops_day.isoformat()}"
