from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.application.shared.sheet_cell_format import (
    format_sheet_date,
    format_sheet_datetime,
    format_sheet_decimal,
    parse_sheet_date,
    parse_sheet_decimal,
)


def test_format_sheet_decimal_uses_comma_for_fractions() -> None:
    # happy
    assert format_sheet_decimal(Decimal("12.5")) == "12,5"


def test_format_sheet_decimal_strips_trailing_zeros() -> None:
    # edge: целое после strip
    assert format_sheet_decimal(Decimal("1304.0")) == "1304"


def test_format_sheet_decimal_keeps_needed_fraction() -> None:
    # happy: 10.50 → 10,5
    assert format_sheet_decimal(Decimal("10.50")) == "10,5"


def test_format_sheet_datetime_zero_pads_hour() -> None:
    # happy: UTC 03:05:04 → Asia/Yekaterinburg (+5) → 08:05:04
    value = datetime(2026, 7, 31, 3, 5, 4, tzinfo=UTC)
    assert format_sheet_datetime(value, ZoneInfo("Asia/Yekaterinburg")) == "31.07.2026 08:05:04"


def test_parse_sheet_decimal_ru_comma_and_percent() -> None:
    # happy: RU comma + optional trailing %
    assert parse_sheet_decimal("12,5") == Decimal("12.5")
    assert parse_sheet_decimal("2,52%") == Decimal("2.52")
    assert parse_sheet_decimal("0,20") == Decimal("0.20")


def test_admin_parse_sheet_decimal_accepts_comma() -> None:
    # happy: admin RU comma via sheet canon
    assert parse_sheet_decimal("12,5") == Decimal("12.5")


def test_parse_sheet_decimal_rejects_garbage() -> None:
    # error
    with pytest.raises(ValueError, match="invalid sheet decimal"):
        parse_sheet_decimal("not-a-number")


def test_parse_sheet_decimal_strips_spaces_and_keeps_dot() -> None:
    # edge: spaces; already-dot; trailing % with spaces
    assert parse_sheet_decimal(" 1 234,50 ") == Decimal("1234.50")
    assert parse_sheet_decimal("10.5") == Decimal("10.5")
    assert parse_sheet_decimal(" 3% ") == Decimal("3")


def test_parse_sheet_decimal_invalid_raises() -> None:
    # error
    with pytest.raises(ValueError):
        parse_sheet_decimal("abc")
    with pytest.raises(ValueError):
        parse_sheet_decimal("")


def test_format_sheet_date_dd_mm_yyyy() -> None:
    # happy: инверсия parse_sheet_date для канона RU-листа
    assert format_sheet_date(date(2026, 6, 1)) == "01.06.2026"


def test_parse_sheet_date_ru_and_iso() -> None:
    # happy
    assert parse_sheet_date("05.08.2026") == date(2026, 8, 5)
    assert parse_sheet_date("2026-08-05") == date(2026, 8, 5)


def test_parse_sheet_date_invalid_raises() -> None:
    # error
    with pytest.raises(ValueError):
        parse_sheet_date("32.01.2026")
    with pytest.raises(ValueError):
        parse_sheet_date("not-a-date")


def test_parse_sheet_decimal_roundtrip_typical_money() -> None:
    # edge: format → parse → format стабилен для типичных денег
    value = Decimal("12.5")
    assert format_sheet_decimal(parse_sheet_decimal(format_sheet_decimal(value))) == "12,5"
