from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data.ms_product_catalog import MsEntityKind, MsProductEntry


@beartype
class CoffeeRecipeProductCatalogDrinkSource:
    def __init__(
        self,
        recipes: CoffeeRecipeRepository,
        products: DomainProductStore,
    ) -> None:
        self._recipes = recipes
        self._products = products

    @beartype
    def list_drink_entries(self) -> Sequence[MsProductEntry]:
        entries: list[MsProductEntry] = []
        for drink_id in self._recipes.list_drink_ids():
            recipe = self._recipes.get(drink_id)
            if recipe is None:
                continue
            drink = self._products.get(drink_id)
            if drink is None or drink.kind != "coffee_drink":
                continue
            legacy = (drink.legacy_ms_code or "").strip()
            if not legacy:
                continue
            name = (recipe.name or drink.name).strip()
            entries.append(
                MsProductEntry(
                    code=legacy,
                    name=name,
                    entity_kind=MsEntityKind.BUNDLE,
                ),
            )
        return entries
