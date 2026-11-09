from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from beartype import beartype


@beartype
def format_sheet_datetime(value: datetime, tz: ZoneInfo) -> str:
    localized = value.astimezone(tz)
    return localized.strftime("%d.%m.%Y %H:%M:%S")


@beartype
def format_sheet_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


@beartype
def format_sheet_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
        if "." in text:
            text = text.replace(".", ",")
    return text


@beartype
def parse_sheet_decimal(raw: str) -> Decimal:
    text = raw.strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    text = text.replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid sheet decimal: {raw!r}") from exc


@beartype
def parse_sheet_date(raw: str) -> date:
    text = raw.strip()
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid sheet date: {raw!r}") from exc
