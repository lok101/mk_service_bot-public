from __future__ import annotations

from decimal import Decimal

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.product_identity.models import DomainProduct
from src.application.reference_data.ms_product_catalog import MsEntityKind
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.infrastructure.reference_data.coffee_recipe_drink_source import (
    CoffeeRecipeProductCatalogDrinkSource,
)
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository


def test_drink_source_lists_legacy_codes_for_drinks_with_recipes() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="drink-1",
            number="D-001",
            name="Latte",
            catalog_code=None,
            hidden=False,
            kind="coffee_drink",
            legacy_ms_code="drink-1",
        ),
    )
    repo = InMemoryCoffeeRecipeRepository()
    repo.upsert(
        CoffeeRecipe(
            drink_product_id="drink-1",
            name="  Latte  ",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id="ing-1",
                    quantity_per_unit=Decimal("1"),
                ),
            ),
        ),
    )
    source = CoffeeRecipeProductCatalogDrinkSource(repo, products)
    entries = source.list_drink_entries()
    assert len(entries) == 1
    assert entries[0].code == "drink-1"
    assert entries[0].name == "Latte"
    assert entries[0].entity_kind is MsEntityKind.BUNDLE


def test_drink_source_omits_drinks_without_recipe() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="drink-1",
            number="D-001",
            name="Latte",
            catalog_code=None,
            hidden=False,
            kind="coffee_drink",
            legacy_ms_code="drink-1",
        ),
    )
    source = CoffeeRecipeProductCatalogDrinkSource(InMemoryCoffeeRecipeRepository(), products)
    assert list(source.list_drink_entries()) == []


def test_drink_source_empty_repo() -> None:
    source = CoffeeRecipeProductCatalogDrinkSource(
        InMemoryCoffeeRecipeRepository(),
        FakeDomainProductStore(),
    )
    assert list(source.list_drink_entries()) == []
