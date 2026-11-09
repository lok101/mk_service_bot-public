from __future__ import annotations

from decimal import Decimal

from src.domain.matrix_pricing.formula import (
    BaseMarginParams,
    calculate_margin_rub,
    calculate_sell_price,
)
from src.domain.matrix_pricing.rounding import round_up_to_last_digits


def _params(**overrides: object) -> BaseMarginParams:
    values: dict[str, object] = {
        "scale_price_min": Decimal("10"),
        "scale_price_max": Decimal("500"),
        "scale_rate_max": Decimal("1.2"),
        "scale_rate_min": Decimal("0.1"),
        "curvature": Decimal("1"),
        "margin_floor": Decimal("20"),
        "rounding_last_digits": None,
    }
    values.update(overrides)
    return BaseMarginParams(**values)  # type: ignore[arg-type]


def test_margin_at_scale_price_min_uses_rate_max() -> None:
    """happy: P = P_min → r = r_max; floor не мешает при большом P*r."""
    params = _params(margin_floor=Decimal("1"))
    # P=10, r=1.2 → margin = 12
    assert calculate_margin_rub(Decimal("10"), params) == Decimal("12")


def test_margin_at_scale_price_max_uses_rate_min() -> None:
    """happy: P = P_max → r = r_min."""
    params = _params(margin_floor=Decimal("1"))
    # P=500, r=0.1 → margin = 50
    assert calculate_margin_rub(Decimal("500"), params) == Decimal("50")


def test_margin_linear_curvature_midpoint() -> None:
    """edge: k=1, середина шкалы — линейная интерполяция r."""
    params = _params(curvature=Decimal("1"), margin_floor=Decimal("1"))
    # t=0.5 → r = 1.2 + (0.1-1.2)*0.5 = 0.65; P=255 → 165.75
    assert calculate_margin_rub(Decimal("255"), params) == Decimal("165.75")


def test_margin_quadratic_curvature_midpoint() -> None:
    """happy: k=2, середина — t^2 = 0.25."""
    params = _params(curvature=Decimal("2"), margin_floor=Decimal("1"))
    # r = 1.2 + (0.1-1.2)*0.25 = 0.925; P=255 → 235.875
    assert calculate_margin_rub(Decimal("255"), params) == Decimal("235.875")


def test_margin_clamps_purchase_below_scale_min() -> None:
    """edge: P < P_min → t=0 → как на якоре min."""
    params = _params(margin_floor=Decimal("1"))
    assert calculate_margin_rub(Decimal("1"), params) == Decimal("1.2")


def test_margin_clamps_purchase_above_scale_max() -> None:
    """edge: P > P_max → t=1 → как на якоре max."""
    params = _params(margin_floor=Decimal("1"))
    assert calculate_margin_rub(Decimal("1000"), params) == Decimal("100")


def test_margin_floor_wins_on_cheap_purchase() -> None:
    """happy: P*r < floor → floor."""
    params = _params(margin_floor=Decimal("20"))
    # P=10, r=1.2 → 12 < 20 → 20
    assert calculate_margin_rub(Decimal("10"), params) == Decimal("20")


def test_margin_fractional_curvature_uses_float_pow() -> None:
    """happy: нецелый k — степень через float, результат в Decimal."""
    params = _params(curvature=Decimal("0.5"), margin_floor=Decimal("1"))
    # P=132.5 → t=0.25; 0.25**0.5 = 0.5; r=0.65; margin=86.125
    assert calculate_margin_rub(Decimal("132.5"), params) == Decimal("86.125")


def test_margin_allows_zero_purchase_without_domain_abort() -> None:
    """edge: P=0 допустим в формуле; merge отсекает через purchase_valid (спек as-is)."""
    params = _params(margin_floor=Decimal("20"))
    margin = calculate_margin_rub(Decimal("0"), params)
    assert margin == Decimal("20")


def test_sell_price_applies_multipliers_and_rounding() -> None:
    """happy: base * product * matrix → round_up_to_last_digits."""
    params = _params(rounding_last_digits=frozenset({4, 9}), margin_floor=Decimal("1"))
    sell = calculate_sell_price(
        purchase=Decimal("10"),
        product_multiplier=Decimal("1.1"),
        matrix_multiplier=Decimal("1"),
        params=params,
    )
    assert isinstance(sell, int)
    expected = round_up_to_last_digits(Decimal("24.2"), frozenset({4, 9}))
    assert sell == expected


def test_decimal_chain_has_no_intermediate_quantize() -> None:
    """edge: цепочка Decimal до финального округления sell."""
    params = _params(
        scale_rate_max=Decimal("0.3333"),
        scale_rate_min=Decimal("0.3333"),
        curvature=Decimal("1"),
        margin_floor=Decimal("1"),
        rounding_last_digits=None,
    )
    sell = calculate_sell_price(
        purchase=Decimal("10.01"),
        product_multiplier=Decimal("1.11"),
        matrix_multiplier=Decimal("1.01"),
        params=params,
    )
    assert isinstance(sell, int)
