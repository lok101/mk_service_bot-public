from __future__ import annotations

import hashlib
from datetime import date

from beartype import beartype

from src.domain.event_reminders.parse import ParsedEventRow


@beartype
def event_key(event_date: date, location: str, comment: str) -> str:
    payload = f"{event_date.isoformat()}|{location}|{comment}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@beartype
def select_events_for_tick(
    events: tuple[ParsedEventRow, ...],
    *,
    today: date,
    lead_days: tuple[int, ...],
) -> tuple[ParsedEventRow, ...]:
    """Filter by lead_days, sort, unique-in-tick by (event_key, days_until)."""
    lead_set = frozenset(lead_days)
    ordered = sorted(
        events,
        key=lambda event: (event.event_date, event.location, event.comment),
    )
    selected: list[ParsedEventRow] = []
    seen: set[tuple[str, int]] = set()
    for event in ordered:
        days_until = (event.event_date - today).days
        if days_until not in lead_set:
            continue
        key = (event_key(event.event_date, event.location, event.comment), days_until)
        if key in seen:
            continue
        seen.add(key)
        selected.append(event)
    return tuple(selected)
