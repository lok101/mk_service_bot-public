from __future__ import annotations

from datetime import date, datetime, time, timedelta

from beartype import beartype

OFFLINE_CHECK_ABSENT = "Проверка «не в сети» не подключена"

__all__ = [
    "OFFLINE_CHECK_ABSENT",
    "history_window",
    "live_group",
    "live_row_note",
    "open_no_sales_session_id",
    "task_suppressed_reason",
]


@beartype
def open_no_sales_session_id(document: dict[str, object]) -> str | None:
    opened = document.get("opened_event_id")
    if isinstance(opened, str) and opened:
        return opened
    if document.get("status") != "open":
        return None
    event_id = document.get("event_id")
    if isinstance(event_id, str) and event_id:
        return event_id
    return None


@beartype
def live_group(*, engineer: bool, muted: bool) -> str:
    if engineer:
        return "engineer"
    if muted:
        return "muted"
    return "problem"


@beartype
def task_suppressed_reason(
    *,
    engineer: bool,
    muted: bool,
    visit_allowed: bool,
    turnover_suppressed: bool,
) -> str | None:
    if engineer:
        return "waiting_engineer"
    if muted:
        return "muted"
    if not visit_allowed:
        return "visit_flag"
    if turnover_suppressed:
        return "turnover"
    return None


@beartype
def live_row_note(*, kind: str, vending_offline: bool) -> str:
    if kind == "micro_market":
        return OFFLINE_CHECK_ABSENT
    if vending_offline:
        return "не на связи"
    return ""


@beartype
def history_window(
    *,
    now: datetime,
    raw_from: str | None,
    raw_to: str | None,
) -> tuple[datetime, datetime]:
    tz = now.tzinfo
    if raw_from is None and raw_to is None:
        day = now.date()
        start = datetime.combine(day - timedelta(days=6), time.min, tzinfo=tz)
        end = datetime.combine(day, time.max, tzinfo=tz)
        return start, end
    start_day = _parse_day(raw_from) if raw_from is not None else now.date() - timedelta(days=6)
    end_day = _parse_day(raw_to) if raw_to is not None else now.date()
    return (
        datetime.combine(start_day, time.min, tzinfo=tz),
        datetime.combine(end_day, time.max, tzinfo=tz),
    )


@beartype
def _parse_day(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid history date: {raw!r}") from exc
