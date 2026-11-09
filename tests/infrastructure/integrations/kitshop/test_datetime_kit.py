from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from src.infrastructure.integrations.kitshop.parsing.datetime_kit import (
    format_kit_datetime,
    parse_kit_datetime,
)

_MOSCOW = ZoneInfo("Europe/Moscow")
_EKB = ZoneInfo("Asia/Yekaterinburg")

# Кабинет +5 показал 16:51; Kit прислал московские 14:51:54.
_SALE_KIT = "05.10.2026 14:51:54"
_SALE_UTC = datetime(2026, 10, 5, 11, 51, 54, tzinfo=UTC)


def test_parse_kit_datetime_reads_moscow_wall_clock() -> None:
    parsed = parse_kit_datetime("04.09.2026 15:30:00")
    assert parsed == datetime(2026, 9, 4, 15, 30, tzinfo=_MOSCOW)
    assert parsed.astimezone(UTC) == datetime(2026, 9, 4, 12, 30, tzinfo=UTC)


def test_parse_kit_datetime_cabinet_plus_5_is_two_hours_later() -> None:
    parsed = parse_kit_datetime(_SALE_KIT)
    assert parsed.tzinfo == _MOSCOW
    assert parsed.astimezone(UTC) == _SALE_UTC
    local = parsed.astimezone(_EKB)
    assert (local.hour, local.minute, local.second) == (16, 51, 54)


def test_format_kit_datetime_filter_uses_moscow_wall_clock() -> None:
    assert format_kit_datetime(_SALE_UTC) == _SALE_KIT


def test_format_kit_datetime_naive_stays_moscow_wall_clock() -> None:
    assert format_kit_datetime(datetime(2026, 10, 5, 14, 51, 54)) == _SALE_KIT


def test_parse_kit_datetime_rejects_non_kit_string() -> None:
    with pytest.raises(ValueError):
        parse_kit_datetime("2026-10-05T14:51:54")
