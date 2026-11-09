from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.domain.calendar import operational_day

_YEKAT = ZoneInfo("Asia/Yekaterinburg")


def test_operational_day_before_end_hour_is_previous_date() -> None:
    value = datetime(2026, 8, 12, 5, 59, tzinfo=_YEKAT)
    assert operational_day(value, _YEKAT, 6).isoformat() == "2026-08-11"


def test_operational_day_at_end_hour_is_same_date() -> None:
    value = datetime(2026, 8, 12, 6, 0, tzinfo=_YEKAT)
    assert operational_day(value, _YEKAT, 6).isoformat() == "2026-08-12"


def test_operational_day_end_hour_zero_is_calendar_date() -> None:
    value = datetime(2026, 8, 12, 0, 0, tzinfo=_YEKAT)
    assert operational_day(value, _YEKAT, 0).isoformat() == "2026-08-12"


def test_operational_day_converts_from_utc() -> None:
    # 01:00 UTC = 06:00 Yekat; naive UTC clock would still be previous operational day.
    value = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
    assert operational_day(value, _YEKAT, 6).isoformat() == "2026-08-12"
