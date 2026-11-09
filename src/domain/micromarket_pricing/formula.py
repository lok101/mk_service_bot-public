from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.domain.matrix_pricing.rounding import round_up_to_last_digits


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPricingRules:
    margin_percent: Decimal
    margin_floor: Decimal
    rounding_last_digits: frozenset[int] | None


@beartype
def calculate_margin_rub(purchase: Decimal, rules: MicromarketPricingRules) -> Decimal:
    percent_margin = purchase * rules.margin_percent / Decimal("100")
    return max(percent_margin, rules.margin_floor)


@beartype
def calculate_sell_price(
    *,
    purchase: Decimal,
    product_multiplier: Decimal,
    machine_multiplier: Decimal,
    rules: MicromarketPricingRules,
) -> int:
    margin_rub = calculate_margin_rub(purchase, rules)
    base = purchase + margin_rub
    raw = base * product_multiplier * machine_multiplier
    return round_up_to_last_digits(raw, rules.rounding_last_digits)
