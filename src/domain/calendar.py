from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

DEFAULT_SERVICE_CALENDAR_TIMEZONE = ZoneInfo("Europe/Moscow")


@beartype
def calendar_anchor(value: datetime, timezone: ZoneInfo) -> datetime:
    day = calendar_day_in_timezone(value, timezone)
    return datetime.combine(day, time.min, tzinfo=timezone)


@beartype
def end_of_service_calendar_day(day: date, timezone: ZoneInfo) -> datetime:
    return datetime.combine(day, time(23, 59, 59, 999999), tzinfo=timezone)


@beartype
def calendar_day_in_timezone(value: datetime, timezone: ZoneInfo) -> date:
    localized = value.astimezone(timezone)
    return localized.date()


@beartype
def operational_day(value: datetime, timezone: ZoneInfo, end_hour: int) -> date:
    localized = value.astimezone(timezone)
    if localized.timetz().replace(tzinfo=None) < time(end_hour, 0):
        return localized.date() - timedelta(days=1)
    return localized.date()


@beartype
def operational_day_window(
    ops_day: date,
    timezone: ZoneInfo,
    end_hour: int,
) -> tuple[datetime, datetime]:
    """UTC-normalized [start, end) for completed_at queries of one operational day."""
    start_local = datetime.combine(ops_day, time(end_hour, 0), tzinfo=timezone)
    end_local = datetime.combine(ops_day + timedelta(days=1), time(end_hour, 0), tzinfo=timezone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


@beartype
def service_timezone_label(timezone: ZoneInfo) -> str:
    if timezone.key == "Europe/Moscow":
        return "МСК"

    sample = datetime.now(tz=UTC).astimezone(timezone)
    abbreviation = sample.tzname()
    if abbreviation:
        return abbreviation

    return timezone.key
