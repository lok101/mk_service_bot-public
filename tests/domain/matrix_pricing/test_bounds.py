from __future__ import annotations

from decimal import Decimal

from src.domain.matrix_pricing.bounds import ProductMultiplierBounds, validate_multiplier
from src.domain.matrix_pricing.errors import MultiplierOutOfBounds


def test_validate_multiplier_in_bounds() -> None:
    bounds = ProductMultiplierBounds(min=Decimal("0.8"), max=Decimal("3.0"))
    assert validate_multiplier(Decimal("1.0"), bounds).is_ok()


def test_validate_multiplier_out_of_bounds() -> None:
    bounds = ProductMultiplierBounds(min=Decimal("0.8"), max=Decimal("3.0"))
    result = validate_multiplier(Decimal("5"), bounds)
    assert result.is_err()
    assert isinstance(result.error, MultiplierOutOfBounds)
