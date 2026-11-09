from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from beartype import beartype

OUTCOME_TECHNICIAN = "техник"
OUTCOME_SELF = "само"
OUTCOME_PENDING = "ещё не ясно"
OUTCOME_MANUAL = "ручной разбор"
OUTCOME_EXCLUDED_MONITORING = "снят из мониторинга"

__all__ = [
    "OUTCOME_EXCLUDED_MONITORING",
    "OUTCOME_MANUAL",
    "OUTCOME_PENDING",
    "OUTCOME_SELF",
    "OUTCOME_TECHNICIAN",
    "no_sales_clearance_outcome",
    "no_sales_episode_clear_kind",
    "select_no_sales_history_documents",
]


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def no_sales_clearance_outcome(
    *,
    clear_trigger: Literal["sale", "exclude"] | None,
    bypass_active: bool,
    last_sale_at: datetime | None,
    maintenance_completed_ats: Sequence[datetime],
    now: datetime,
    pair_minutes: int,
) -> str:
    if bypass_active:
        return OUTCOME_MANUAL
    if clear_trigger == "exclude":
        return OUTCOME_EXCLUDED_MONITORING
    if last_sale_at is None:
        return OUTCOME_SELF
    sale = _as_utc(last_sale_at)
    window = timedelta(minutes=pair_minutes)
    for raw in maintenance_completed_ats:
        completed = _as_utc(raw)
        if abs(completed - sale) <= window:
            return OUTCOME_TECHNICIAN
    if _as_utc(now) < sale + window:
        return OUTCOME_PENDING
    return OUTCOME_SELF


@beartype
def no_sales_episode_clear_kind(
    *,
    cleared_at: datetime | None,
    clear_trigger: Literal["sale", "exclude"] | None,
    bypass_active: bool | None,
    last_sale_at: datetime | None,
    maintenance_completed_ats: Sequence[datetime],
    now: datetime,
    pair_minutes: int,
) -> str:
    if cleared_at is None:
        return "—"
    if clear_trigger in ("sale", "exclude"):
        return no_sales_clearance_outcome(
            clear_trigger=clear_trigger,
            bypass_active=False if bypass_active is None else bypass_active,
            last_sale_at=last_sale_at,
            maintenance_completed_ats=maintenance_completed_ats,
            now=now,
            pair_minutes=pair_minutes,
        )
    if last_sale_at is not None:
        return no_sales_clearance_outcome(
            clear_trigger="sale",
            bypass_active=False,
            last_sale_at=last_sale_at,
            maintenance_completed_ats=maintenance_completed_ats,
            now=now,
            pair_minutes=pair_minutes,
        )
    return "cleared"


@beartype
def _moment_in_period(value: object, *, start: datetime, end: datetime) -> bool:
    return isinstance(value, datetime) and start <= value <= end


@beartype
def _opened_event_id(document: dict[str, object]) -> str | None:
    opened = document.get("opened_event_id")
    if isinstance(opened, str) and opened:
        return opened
    return None


@beartype
def select_no_sales_history_documents(
    *,
    episodes: Sequence[dict[str, object]],
    open_documents: Sequence[dict[str, object]],
    cleared_documents: Sequence[dict[str, object]],
    start: datetime,
    end: datetime,
) -> list[dict[str, object]]:
    filtered_episodes = [
        dict(document)
        for document in episodes
        if _moment_in_period(document.get("opened_at"), start=start, end=end)
        or _moment_in_period(document.get("cleared_at"), start=start, end=end)
    ]
    filtered_open = [
        dict(document)
        for document in open_documents
        if _moment_in_period(document.get("opened_at"), start=start, end=end)
    ]
    filtered_cleared = [
        dict(document)
        for document in cleared_documents
        if _moment_in_period(document.get("opened_at"), start=start, end=end)
        or _moment_in_period(document.get("cleared_at"), start=start, end=end)
    ]
    episode_ids = {
        opened_id
        for document in filtered_episodes
        if (opened_id := _opened_event_id(document)) is not None
    }
    result = list(filtered_episodes)
    for document in filtered_open:
        opened_id = _opened_event_id(document)
        if opened_id is not None and opened_id in episode_ids:
            continue
        result.append(document)
    for document in filtered_cleared:
        opened_id = _opened_event_id(document)
        if opened_id is not None and opened_id in episode_ids:
            continue
        result.append(document)
    return result
