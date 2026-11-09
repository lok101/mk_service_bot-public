from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.technician_settlement.audit_format import (
    format_audit_datetime,
    format_audit_decimal,
    format_delta_pct,
)


def test_format_audit_datetime_moscow() -> None:
    value = datetime(2026, 6, 1, 12, 33, tzinfo=UTC)
    assert format_audit_datetime(value, ZoneInfo("Europe/Moscow")) == "01.06.2026 15:33:00"


def test_format_delta_pct_signed() -> None:
    assert format_delta_pct(Decimal("-240"), Decimal("1000")) == "-24,0%"


def test_format_delta_pct_empty_when_sales_zero() -> None:
    assert format_delta_pct(Decimal("-1"), Decimal("0")) == ""


def test_format_audit_decimal_strips_trailing_zeros() -> None:
    assert format_audit_decimal(Decimal("1304.0")) == "1304"


def test_format_audit_decimal_uses_comma_for_fractions() -> None:
    assert format_audit_decimal(Decimal("12.5")) == "12,5"
