from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.domain.matrix_pricing.rounding import round_up_to_last_digits


@beartype
@dataclass(frozen=True, slots=True)
class BaseMarginParams:
    scale_price_min: Decimal
    scale_price_max: Decimal
    scale_rate_max: Decimal
    scale_rate_min: Decimal
    curvature: Decimal
    margin_floor: Decimal
    rounding_last_digits: frozenset[int] | None


@beartype
def calculate_margin_rub(purchase: Decimal, params: BaseMarginParams) -> Decimal:
    span = params.scale_price_max - params.scale_price_min
    t = (purchase - params.scale_price_min) / span
    if t < 0:
        t = Decimal("0")
    elif t > 1:
        t = Decimal("1")
    # float только для степени t^k (спек); остальная цепочка — Decimal
    curved = Decimal(str(float(t) ** float(params.curvature)))
    rate = params.scale_rate_max + (params.scale_rate_min - params.scale_rate_max) * curved
    return max(purchase * rate, params.margin_floor)


@beartype
def calculate_sell_price(
    *,
    purchase: Decimal,
    product_multiplier: Decimal,
    matrix_multiplier: Decimal,
    params: BaseMarginParams,
) -> int:
    margin_rub = calculate_margin_rub(purchase, params)
    base = purchase + margin_rub
    raw = base * product_multiplier * matrix_multiplier
    digits: frozenset[int] | None = params.rounding_last_digits
    return round_up_to_last_digits(raw, digits)
