from __future__ import annotations

from decimal import Decimal

from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository

_LATTE = CoffeeRecipe(
    drink_product_id="drink-1",
    name="Latte",
    components=(
        CoffeeRecipeComponent(
            ingredient_product_id="ing-1",
            quantity_per_unit=Decimal("12.5"),
        ),
    ),
)


def test_upsert_and_get_by_drink_ids() -> None:
    repo = InMemoryCoffeeRecipeRepository()
    repo.upsert(_LATTE)

    loaded = repo.get_by_drink_ids(frozenset({"drink-1"}))

    assert loaded["drink-1"].name == "Latte"


def test_get_returns_none_for_missing_drink() -> None:
    repo = InMemoryCoffeeRecipeRepository()

    assert repo.get("missing") is None


def test_list_drink_ids_returns_sorted_ids() -> None:
    repo = InMemoryCoffeeRecipeRepository()
    repo.upsert(_LATTE)
    repo.upsert(
        CoffeeRecipe(
            drink_product_id="drink-2",
            name="Espresso",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id="ing-1",
                    quantity_per_unit=Decimal("10"),
                ),
            ),
        ),
    )

    assert repo.list_drink_ids() == ("drink-1", "drink-2")
