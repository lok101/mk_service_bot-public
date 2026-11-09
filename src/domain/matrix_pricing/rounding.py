from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from beartype import beartype


@beartype
def _decimal_ceil_to_int(raw: Decimal) -> int:
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


@beartype
def round_up_to_last_digits(
    raw: Decimal,
    allowed_digits: frozenset[int] | None,
) -> int:
    if allowed_digits is None or len(allowed_digits) == 0:
        return _decimal_ceil_to_int(raw)

    normalized = frozenset(allowed_digits)
    ceiling = _decimal_ceil_to_int(raw)
    candidate = ceiling
    while candidate % 10 not in normalized:
        candidate += 1
    return candidate
