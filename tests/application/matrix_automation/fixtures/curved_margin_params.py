from __future__ import annotations

from decimal import Decimal

from src.domain.matrix_pricing.formula import BaseMarginParams


def curved_margin_params(
    *,
    rounding_last_digits: frozenset[int] | None = None,
    **overrides: Decimal | frozenset[int] | None,
) -> BaseMarginParams:
    """VO, эквивалентный старому flat max(P*0.2, 20) при равных rate и k=1."""
    values: dict[str, object] = {
        "scale_price_min": Decimal("10"),
        "scale_price_max": Decimal("500"),
        "scale_rate_max": Decimal("0.2"),
        "scale_rate_min": Decimal("0.2"),
        "curvature": Decimal("1"),
        "margin_floor": Decimal("20"),
        "rounding_last_digits": rounding_last_digits,
    }
    values.update(overrides)
    return BaseMarginParams(**values)  # type: ignore[arg-type]
