from __future__ import annotations

from decimal import Decimal

from src.domain.micromarket_pricing.bounds import (
    MachineMultiplierBounds,
    ProductMultiplierBounds,
    validate_multiplier,
)
from src.domain.micromarket_pricing.errors import MultiplierOutOfBounds


def test_validate_multiplier_ok_inside_bounds() -> None:
    """happy: value in [min, max]."""
    result = validate_multiplier(
        Decimal("1.5"),
        ProductMultiplierBounds(min=Decimal("0.8"), max=Decimal("3.0")),
    )
    assert result.is_ok()
    assert result.value == Decimal("1.5")


def test_validate_multiplier_err_below_min() -> None:
    """error: below min."""
    result = validate_multiplier(
        Decimal("0.5"),
        MachineMultiplierBounds(min=Decimal("0.8"), max=Decimal("3.0")),
    )
    assert result.is_err()
    assert isinstance(result.error, MultiplierOutOfBounds)


def test_validate_multiplier_err_above_max() -> None:
    """error: above max."""
    result = validate_multiplier(
        Decimal("3.5"),
        ProductMultiplierBounds(min=Decimal("0.8"), max=Decimal("3.0")),
    )
    assert result.is_err()
