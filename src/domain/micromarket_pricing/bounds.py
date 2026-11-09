from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.domain.micromarket_pricing.errors import MultiplierOutOfBounds
from src.domain.micromarket_pricing.result import Result


@beartype
@dataclass(frozen=True, slots=True)
class ProductMultiplierBounds:
    min: Decimal
    max: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class MachineMultiplierBounds:
    min: Decimal
    max: Decimal


@beartype
def validate_multiplier(
    value: Decimal,
    bounds: ProductMultiplierBounds | MachineMultiplierBounds,
) -> Result[Decimal, MultiplierOutOfBounds]:
    if bounds.min <= value <= bounds.max:
        return Result.ok(value)
    return Result.err(
        MultiplierOutOfBounds(
            value=str(value),
            min_bound=str(bounds.min),
            max_bound=str(bounds.max),
        ),
    )
