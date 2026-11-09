from __future__ import annotations

from beartype import beartype

from src.application.product_identity import catalog_codes_of
from src.application.product_identity.ports import DomainProductStore
from src.domain.coffee_bom.models import CoffeeRecipe


@beartype
def validate_recipe_components_against_catalog(
    recipe: CoffeeRecipe,
    *,
    products: DomainProductStore,
) -> None:
    """ValueError if ingredient missing, wrong kind, or has no MS catalog link."""
    missing: list[str] = []
    for component in recipe.components:
        product = products.get(component.ingredient_product_id)
        if product is None or product.kind != "coffee_ingredient":
            missing.append(component.ingredient_product_id)
            continue
        if not catalog_codes_of(product):
            missing.append(component.ingredient_product_id)
    if missing:
        sorted_ids = ", ".join(sorted(set(missing)))
        raise ValueError(
            f"Unknown or unlinked coffee ingredients for drink "
            f"{recipe.drink_product_id!r}: {sorted_ids}.",
        )
