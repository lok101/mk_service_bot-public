from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

# Только Kit Vending (как kit-api LibDateTime). Kit Shop SaleDateTime — Europe/Moscow,
# см. kitshop/parsing/datetime_kit.py. Этот пояс туда не переносить.
_PROJECT_TIMEZONE = ZoneInfo("Asia/Yekaterinburg")


class KitDateTime:
    _KIT_API_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"

    @classmethod
    @beartype
    def datetime_to_str_kit(cls, dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_PROJECT_TIMEZONE)
        else:
            dt = dt.astimezone(_PROJECT_TIMEZONE)
        return dt.strftime(cls._KIT_API_DATETIME_FORMAT)

    @classmethod
    @beartype
    def datetime_from_str_kit(cls, val: str) -> datetime:
        dt = datetime.strptime(val, cls._KIT_API_DATETIME_FORMAT)
        return dt.replace(tzinfo=_PROJECT_TIMEZONE)
