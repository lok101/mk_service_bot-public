from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from beartype import beartype

_TWOPLACES = Decimal("0.01")


@beartype
def round_money(value: Decimal) -> Decimal:
    return value.quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
