from __future__ import annotations

from decimal import Decimal

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.product_identity.models import DomainProduct
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository


def seed_latte_bom(
    *,
    coffee_qty: str = "30",
    drink_id: str = "drink-latte",
    ingredient_id: str = "ing-coffee",
    legacy_ms_code: str = "2301",
    ingredient_ms_code: str = "coffee-1",
    products: FakeDomainProductStore | None = None,
    recipes: InMemoryCoffeeRecipeRepository | None = None,
) -> tuple[FakeDomainProductStore, InMemoryCoffeeRecipeRepository]:
    store = products if products is not None else FakeDomainProductStore()
    repo = recipes if recipes is not None else InMemoryCoffeeRecipeRepository()
    if store.get(drink_id) is None:
        store.insert(
            DomainProduct(
                domain_product_id=drink_id,
                number="D-LATTE",
                name="Latte",
                catalog_code=None,
                hidden=False,
                kind="coffee_drink",
                legacy_ms_code=legacy_ms_code,
            ),
        )
    if store.get(ingredient_id) is None:
        store.insert(
            DomainProduct(
                domain_product_id=ingredient_id,
                number="I-COFFEE",
                name="Coffee",
                catalog_code=ingredient_ms_code,
                hidden=False,
                kind="coffee_ingredient",
            ),
        )
    repo.upsert(
        CoffeeRecipe(
            drink_product_id=drink_id,
            name="Latte",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id=ingredient_id,
                    quantity_per_unit=Decimal(coffee_qty),
                ),
            ),
        ),
    )
    return store, repo
