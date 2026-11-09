from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

# Kit Shop SaleDateTime и фильтр GetSales (UpDate/ToDate) — наивные
# «дд.мм.гггг чч:мм:сс» в Europe/Moscow (UTC+3), как GetVMStates.DateTime.
# Пояс кабинета сюда не подставлять: кабинет +5 показывает на 2 часа больше.
# Не копировать Asia/Yekaterinburg из kitvending/datetime_kit.py — это другой контур.
_KIT_API_TIMEZONE = ZoneInfo("Europe/Moscow")
_KIT_API_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"


@beartype
def parse_kit_datetime(value: str) -> datetime:
    """Parse Kit Shop naive ``dd.MM.yyyy HH:mm:ss`` as Europe/Moscow (not UTC)."""
    dt = datetime.strptime(value, _KIT_API_DATETIME_FORMAT)
    return dt.replace(tzinfo=_KIT_API_TIMEZONE)


@beartype
def format_kit_datetime(dt: datetime) -> str:
    """Format datetime for Kit Shop GetSales filter (Europe/Moscow wall clock)."""
    if dt.tzinfo is None:
        local = dt.replace(tzinfo=_KIT_API_TIMEZONE)
    else:
        local = dt.astimezone(_KIT_API_TIMEZONE)
    return local.strftime(_KIT_API_DATETIME_FORMAT)
