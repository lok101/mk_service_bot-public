from __future__ import annotations

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from src.domain.calendar import operational_day, operational_day_window

_TZ = ZoneInfo("Asia/Yekaterinburg")
_END_HOUR = 6
_OPS_DAY = date(2026, 8, 12)


def test_operational_day_window_matches_operational_day_membership() -> None:
    start, end = operational_day_window(_OPS_DAY, _TZ, _END_HOUR)
    assert start < end

    inside = start + timedelta(minutes=1)
    outside_before = start - timedelta(seconds=1)
    outside_after = end

    assert operational_day(inside, _TZ, _END_HOUR) == _OPS_DAY
    assert operational_day(outside_before, _TZ, _END_HOUR) != _OPS_DAY
    assert operational_day(outside_after, _TZ, _END_HOUR) != _OPS_DAY


def test_operational_day_window_start_is_end_hour_local() -> None:
    start, _ = operational_day_window(_OPS_DAY, _TZ, _END_HOUR)
    local = start.astimezone(_TZ)
    assert local.date() == _OPS_DAY
    assert local.timetz().replace(tzinfo=None) == time(_END_HOUR, 0)


def test_operational_day_window_boundary_event_at_start_counts_in_ops_day() -> None:
    start, _ = operational_day_window(_OPS_DAY, _TZ, _END_HOUR)
    assert operational_day(start, _TZ, _END_HOUR) == _OPS_DAY
