from __future__ import annotations

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.product_identity.ports import DomainProductStore
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent


@beartype
def upsert_coffee_recipe(
    drink_product_id: str,
    components: tuple[CoffeeRecipeComponent, ...],
    *,
    recipe_repo: CoffeeRecipeRepository,
    products: DomainProductStore,
    name: str | None = None,
    legacy_bundle_code: str | None = None,
) -> CoffeeRecipe:
    drink = products.get(drink_product_id)
    if drink is None or drink.kind != "coffee_drink":
        raise ValueError(f"Unknown coffee drink {drink_product_id!r}")
    for component in components:
        if component.quantity_per_unit <= 0:
            raise ValueError(
                f"quantity_per_unit must be > 0 for ingredient {component.ingredient_product_id!r}",
            )
        ingredient = products.get(component.ingredient_product_id)
        if ingredient is None or ingredient.kind != "coffee_ingredient":
            raise ValueError(
                f"Unknown coffee ingredient {component.ingredient_product_id!r}",
            )
    recipe = CoffeeRecipe(
        drink_product_id=drink_product_id,
        components=components,
        name=name if name is not None else drink.name,
    )
    recipe_repo.upsert(recipe, legacy_bundle_code=legacy_bundle_code)
    return recipe
