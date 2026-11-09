from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

_MOMENT = "%d.%m.%y %H:%M"
_SORT = "%Y%m%d%H%M%S%f"

__all__ = ["admin_moment_sort_key", "format_admin_moment"]


@beartype
def format_admin_moment(moment: datetime | None, timezone: ZoneInfo) -> str:
    aware = _as_utc(moment)
    if aware is None:
        return "—"
    return aware.astimezone(timezone).strftime(_MOMENT)


@beartype
def admin_moment_sort_key(moment: datetime | None) -> str:
    aware = _as_utc(moment)
    if aware is None:
        return ""
    return aware.astimezone(UTC).strftime(_SORT)


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
