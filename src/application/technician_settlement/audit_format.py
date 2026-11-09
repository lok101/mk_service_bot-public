from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.shared.sheet_cell_format import (
    format_sheet_datetime,
    format_sheet_decimal,
)


@beartype
def format_audit_datetime(value: datetime, tz: ZoneInfo) -> str:
    return format_sheet_datetime(value, tz)


@beartype
def format_audit_decimal(value: Decimal) -> str:
    return format_sheet_decimal(value)


@beartype
def format_delta_pct(delta: Decimal, sales_total: Decimal) -> str:
    if sales_total == Decimal("0"):
        return ""
    pct = (delta / sales_total) * Decimal("100")
    quantized = pct.quantize(Decimal("0.1"))
    return f"{quantized}%".replace(".", ",")
