from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.coffee_bom.models import CoffeeRecipe


@runtime_checkable
class CoffeeRecipeRepository(Protocol):
    @beartype
    def get_by_drink_ids(self, drink_ids: frozenset[str]) -> dict[str, CoffeeRecipe]: ...

    @beartype
    def upsert(self, recipe: CoffeeRecipe, *, legacy_bundle_code: str | None = None) -> None: ...

    @beartype
    def get(self, drink_product_id: str) -> CoffeeRecipe | None: ...

    @beartype
    def list_drink_ids(self) -> tuple[str, ...]: ...
