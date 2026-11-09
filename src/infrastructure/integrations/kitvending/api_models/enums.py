from __future__ import annotations

from enum import IntEnum, StrEnum


class ResultCode(IntEnum):
    SUCCESS = 0
    INVALID_REQUEST_ID = 14
    TOO_MANY_REQUEST = 27


class VendingMachineKind(StrEnum):
    """Тип линейки автомата по коду в названии ([5xx] — снековый)."""

    NOT_DEFINED = "not_defined"
    SNACK = "snack"
    COFFEE = "coffee"
