from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

ComponentEntityType = Literal["product", "variant"]


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeRecipeComponent:
    ingredient_product_id: str
    quantity_per_unit: Decimal
    entity_type: ComponentEntityType | None = None


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeRecipe:
    drink_product_id: str
    components: tuple[CoffeeRecipeComponent, ...]
    name: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class UnresolvedCoffeeRecipes:
    bundle_codes: tuple[str, ...]
