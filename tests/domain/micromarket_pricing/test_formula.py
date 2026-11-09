from __future__ import annotations

from decimal import Decimal

from src.domain.micromarket_pricing.formula import (
    MicromarketPricingRules,
    calculate_margin_rub,
    calculate_sell_price,
)


def _rules(**overrides: object) -> MicromarketPricingRules:
    values: dict[str, object] = {
        "margin_percent": Decimal("50"),
        "margin_floor": Decimal("20"),
        "rounding_last_digits": None,
    }
    values.update(overrides)
    return MicromarketPricingRules(**values)  # type: ignore[arg-type]


def test_margin_percent_wins_when_above_floor() -> None:
    """happy: P*%/100 >= floor → percent margin."""
    # P=100, 50% → 50 > 20
    assert calculate_margin_rub(Decimal("100"), _rules()) == Decimal("50")


def test_margin_floor_wins_on_cheap_purchase() -> None:
    """happy: P*%/100 < floor → floor."""
    # P=20, 50% → 10 < 20 → 20
    assert calculate_margin_rub(Decimal("20"), _rules()) == Decimal("20")


def test_sell_price_applies_multipliers_and_ceil() -> None:
    """happy: (P+margin)*product*machine, ceil to rub when no digits."""
    # P=100, margin=50 → base=150; *1.1*1.2=198 → 198
    sell = calculate_sell_price(
        purchase=Decimal("100"),
        product_multiplier=Decimal("1.1"),
        machine_multiplier=Decimal("1.2"),
        rules=_rules(),
    )
    assert sell == 198


def test_sell_price_default_multipliers_are_one() -> None:
    """edge: missing mult treated as 1 by caller; here explicit 1."""
    # P=100, margin=50 → 150
    sell = calculate_sell_price(
        purchase=Decimal("100"),
        product_multiplier=Decimal("1"),
        machine_multiplier=Decimal("1"),
        rules=_rules(),
    )
    assert sell == 150


def test_sell_price_rounding_last_digits() -> None:
    """happy: round up to allowed last digit."""
    # raw ≈ 150.1 → ceil path with digits {0,5} → 155
    sell = calculate_sell_price(
        purchase=Decimal("100"),
        product_multiplier=Decimal("1"),
        machine_multiplier=Decimal("1.001"),
        rules=_rules(rounding_last_digits=frozenset({0, 5})),
    )
    assert sell % 10 in {0, 5}
    assert sell >= 150
