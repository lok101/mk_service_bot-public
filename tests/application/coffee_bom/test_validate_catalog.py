from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.coffee_bom.validate_catalog import (
    validate_recipe_components_against_catalog,
)
from src.application.product_identity.models import DomainProduct
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent


def test_validate_recipe_components_against_catalog_ok() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="ing-1",
            number="I-1",
            name="Coffee",
            catalog_code="16161616003327",
            hidden=False,
            kind="coffee_ingredient",
        ),
    )
    recipe = CoffeeRecipe(
        drink_product_id="drink-1",
        name="Latte",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="ing-1",
                quantity_per_unit=Decimal("12"),
            ),
        ),
    )
    validate_recipe_components_against_catalog(recipe, products=store)


def test_validate_recipe_components_against_catalog_missing() -> None:
    store = FakeDomainProductStore()
    recipe = CoffeeRecipe(
        drink_product_id="drink-1",
        name="Latte",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="missing",
                quantity_per_unit=Decimal("1"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="Unknown or unlinked coffee ingredients"):
        validate_recipe_components_against_catalog(recipe, products=store)
