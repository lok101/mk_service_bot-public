from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.interfaces.admin.clock_display import admin_moment_sort_key, format_admin_moment

__all__ = [
    "IncidentHistoryRowView",
    "incident_history_choices",
    "incident_open_duration_hours",
    "present_incident_history_row",
]


@beartype
@dataclass(frozen=True, slots=True)
class IncidentHistoryRowView:
    machine_id: str
    name: str
    opened_at: str
    opened_sort: str
    cleared_at: str
    cleared_sort: str
    duration_hours: str
    duration_sort: str
    technician: str
    reason: str
    clear_kind: str


@beartype
def incident_open_duration_hours(
    opened_at: datetime | None,
    cleared_at: datetime | None,
) -> int | None:
    if opened_at is None or cleared_at is None:
        return None
    opened = opened_at if opened_at.tzinfo is not None else opened_at.replace(tzinfo=UTC)
    cleared = cleared_at if cleared_at.tzinfo is not None else cleared_at.replace(tzinfo=UTC)
    opened = opened.astimezone(UTC)
    cleared = cleared.astimezone(UTC)
    if cleared < opened:
        return None
    return int((cleared - opened) // timedelta(hours=1))


@beartype
def present_incident_history_row(
    *,
    machine_id: str,
    name: str,
    opened_at: datetime | None,
    cleared_at: datetime | None,
    technician: str,
    reason: str | None,
    clear_kind: str,
    timezone: ZoneInfo,
) -> IncidentHistoryRowView:
    hours = incident_open_duration_hours(opened_at, cleared_at)
    return IncidentHistoryRowView(
        machine_id=machine_id,
        name=name or "—",
        opened_at=format_admin_moment(opened_at, timezone),
        opened_sort=admin_moment_sort_key(opened_at),
        cleared_at=format_admin_moment(cleared_at, timezone),
        cleared_sort=admin_moment_sort_key(cleared_at),
        duration_hours="—" if hours is None else str(hours),
        duration_sort="" if hours is None else str(hours),
        technician=technician or "—",
        reason=reason or "—",
        clear_kind=clear_kind or "—",
    )


@beartype
def incident_history_choices(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=str.casefold))
