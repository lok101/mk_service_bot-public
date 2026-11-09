from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from beartype import beartype

from src.infrastructure.integrations.moysklad.exceptions import MoySkladValidationError

_PROJECT_TIMEZONE = timezone(timedelta(hours=3))


@beartype
def parse_moment(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value)
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


@beartype
def format_moment(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise MoySkladValidationError("Необходимо указать tz у объекта datetime.")
    localized = moment.astimezone(_PROJECT_TIMEZONE)
    return localized.replace(tzinfo=None, microsecond=0).isoformat(sep=" ")
