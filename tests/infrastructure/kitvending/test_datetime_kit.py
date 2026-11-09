from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.infrastructure.integrations.kitvending.datetime_kit import KitDateTime

_EKB = ZoneInfo("Asia/Yekaterinburg")


def test_datetime_from_str_kit_is_aware_yekaterinburg() -> None:
    dt = KitDateTime.datetime_from_str_kit("01.05.2026 12:00:00")
    assert dt.tzinfo == _EKB
    assert dt.hour == 12


def test_datetime_to_utc_from_kit_str() -> None:
    dt = KitDateTime.datetime_from_str_kit("01.05.2026 12:00:00")
    utc = dt.astimezone(UTC)
    assert utc.tzinfo == UTC


def test_datetime_to_str_kit_from_utc() -> None:
    dt = datetime(2026, 5, 1, 7, 0, 0, tzinfo=UTC)  # 12:00 EKB (+5)
    assert KitDateTime.datetime_to_str_kit(dt) == "01.05.2026 12:00:00"
