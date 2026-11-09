from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.domain.coffee_bom.models import CoffeeRecipe


@beartype
@dataclass
class InMemoryCoffeeRecipeRepository:
    _by_drink_id: dict[str, CoffeeRecipe] = field(default_factory=dict)

    @beartype
    def get_by_drink_ids(self, drink_ids: frozenset[str]) -> dict[str, CoffeeRecipe]:
        return {
            drink_id: self._by_drink_id[drink_id]
            for drink_id in drink_ids
            if drink_id in self._by_drink_id
        }

    @beartype
    def upsert(self, recipe: CoffeeRecipe, *, legacy_bundle_code: str | None = None) -> None:
        _ = legacy_bundle_code
        self._by_drink_id[recipe.drink_product_id] = recipe

    @beartype
    def get(self, drink_product_id: str) -> CoffeeRecipe | None:
        return self._by_drink_id.get(drink_product_id)

    @beartype
    def list_drink_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_drink_id))
