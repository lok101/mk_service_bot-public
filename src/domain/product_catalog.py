from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto

from beartype import beartype


@beartype
class ProductUnit(Enum):
    GRAM = auto()
    KILOGRAM = auto()
    MILLILITER = auto()
    PIECE = auto()


@beartype
def default_moysklad_quantity_factor(unit: ProductUnit) -> Decimal:
    """Multiply catalog (form) quantity by this factor to get MoySklad API quantity."""
    if unit in {ProductUnit.GRAM, ProductUnit.MILLILITER}:
        return Decimal("0.001")
    return Decimal("1")


@beartype
@dataclass(frozen=True, slots=True)
class ProductSpec:
    product_code: str
    name: str
    unit: ProductUnit
    pack_size: Decimal | None
    min_stock: Decimal | None
    max_stock: Decimal | None
    allow_fraction: bool
    moysklad_quantity_factor: Decimal

    def __post_init__(self) -> None:
        if self.moysklad_quantity_factor <= 0:
            raise ValueError("moysklad_quantity_factor must be positive")
