from __future__ import annotations

from decimal import Decimal

from beartype import beartype

OPEX_BREAKDOWN_KEYS: tuple[str, ...] = (
    "rent_fixed",
    "rent_percent",
    "patent",
    "tax",
    "acquiring_percent",
    "acquiring_per_sale",
    "terminal",
    "labor",
    "route_fuel",
)


@beartype
def empty_opex_breakdown() -> tuple[tuple[str, Decimal | None], ...]:
    zero = Decimal("0.00")
    return tuple((k, zero) for k in OPEX_BREAKDOWN_KEYS)
