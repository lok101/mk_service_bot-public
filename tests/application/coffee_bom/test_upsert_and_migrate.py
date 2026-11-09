from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.coffee_bom.commands import upsert_coffee_recipe
from src.application.coffee_bom.migrate_legacy_recipes import (
    LegacyCoffeeRecipe,
    LegacyCoffeeRecipeComponent,
    migrate_legacy_recipes,
)
from src.application.product_identity.models import DomainProduct
from src.domain.coffee_bom.models import CoffeeRecipeComponent
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository

_DRINK = DomainProduct(
    domain_product_id="drink-1",
    number="D-001",
    name="Latte",
    catalog_code=None,
    hidden=False,
    kind="coffee_drink",
    legacy_ms_code="2301",
)
_ING = DomainProduct(
    domain_product_id="ing-1",
    number="I-001",
    name="Coffee",
    catalog_code="coffee-1",
    hidden=False,
    kind="coffee_ingredient",
)
_MILK = DomainProduct(
    domain_product_id="ing-2",
    number="I-002",
    name="Milk",
    catalog_code="milk-1",
    hidden=False,
    kind="coffee_ingredient",
)


def test_upsert_and_get_by_drink_id() -> None:
    store = FakeDomainProductStore()
    store.insert(_DRINK)
    store.insert(_ING)
    repo = InMemoryCoffeeRecipeRepository()

    upsert_coffee_recipe(
        drink_product_id="drink-1",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="ing-1",
                quantity_per_unit=Decimal("12.5"),
            ),
        ),
        name="Latte",
        recipe_repo=repo,
        products=store,
    )

    loaded = repo.get("drink-1")
    assert loaded is not None
    assert loaded.drink_product_id == "drink-1"
    assert loaded.name == "Latte"
    assert loaded.components[0].ingredient_product_id == "ing-1"
    assert repo.get_by_drink_ids(frozenset({"drink-1"}))["drink-1"].name == "Latte"


def test_upsert_rejects_unknown_ingredient() -> None:
    store = FakeDomainProductStore()
    store.insert(_DRINK)
    repo = InMemoryCoffeeRecipeRepository()

    with pytest.raises(ValueError, match="ingredient"):
        upsert_coffee_recipe(
            drink_product_id="drink-1",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id="missing",
                    quantity_per_unit=Decimal("1"),
                ),
            ),
            recipe_repo=repo,
            products=store,
        )


def test_upsert_rejects_non_drink() -> None:
    store = FakeDomainProductStore()
    store.insert(_ING)
    repo = InMemoryCoffeeRecipeRepository()

    with pytest.raises(ValueError, match="drink"):
        upsert_coffee_recipe(
            drink_product_id="ing-1",
            components=(),
            recipe_repo=repo,
            products=store,
        )


def test_migrate_mapped_legacy_recipe() -> None:
    store = FakeDomainProductStore()
    store.insert(_DRINK)
    store.insert(_ING)
    store.insert(_MILK)
    repo = InMemoryCoffeeRecipeRepository()
    legacy = (
        LegacyCoffeeRecipe(
            bundle_code="2301",
            name="Latte",
            components=(
                LegacyCoffeeRecipeComponent(
                    product_code="coffee-1",
                    quantity_per_unit=Decimal("12.5"),
                ),
                LegacyCoffeeRecipeComponent(
                    product_code="milk-1",
                    quantity_per_unit=Decimal("100"),
                ),
            ),
        ),
    )

    report = migrate_legacy_recipes(legacy, products=store, recipe_repo=repo)

    assert report.migrated == 1
    assert report.gaps == ()
    recipe = repo.get("drink-1")
    assert recipe is not None
    assert recipe.name == "Latte"
    assert {c.ingredient_product_id for c in recipe.components} == {"ing-1", "ing-2"}


def test_migrate_reports_missing_drink_for_bundle() -> None:
    store = FakeDomainProductStore()
    store.insert(_ING)
    repo = InMemoryCoffeeRecipeRepository()
    legacy = (
        LegacyCoffeeRecipe(
            bundle_code="9999",
            name="Ghost",
            components=(
                LegacyCoffeeRecipeComponent(
                    product_code="coffee-1",
                    quantity_per_unit=Decimal("1"),
                ),
            ),
        ),
    )

    report = migrate_legacy_recipes(legacy, products=store, recipe_repo=repo)

    assert report.migrated == 0
    assert len(report.gaps) == 1
    assert "9999" in report.gaps[0]
    assert repo.list_drink_ids() == ()


def test_migrate_reports_missing_ingredient_link() -> None:
    store = FakeDomainProductStore()
    store.insert(_DRINK)
    repo = InMemoryCoffeeRecipeRepository()
    legacy = (
        LegacyCoffeeRecipe(
            bundle_code="2301",
            name="Latte",
            components=(
                LegacyCoffeeRecipeComponent(
                    product_code="orphan-ms",
                    quantity_per_unit=Decimal("1"),
                ),
            ),
        ),
    )

    report = migrate_legacy_recipes(legacy, products=store, recipe_repo=repo)

    assert report.migrated == 0
    assert any("orphan-ms" in gap for gap in report.gaps)
    assert repo.get("drink-1") is None


def test_migrate_allow_partial_writes_complete_recipes_only() -> None:
    store = FakeDomainProductStore()
    store.insert(_DRINK)
    store.insert(_ING)
    other_drink = DomainProduct(
        domain_product_id="drink-2",
        number="D-002",
        name="Espresso",
        catalog_code=None,
        hidden=False,
        kind="coffee_drink",
        legacy_ms_code="2302",
    )
    store.insert(other_drink)
    repo = InMemoryCoffeeRecipeRepository()
    legacy = (
        LegacyCoffeeRecipe(
            bundle_code="2301",
            name="Latte",
            components=(
                LegacyCoffeeRecipeComponent(
                    product_code="coffee-1",
                    quantity_per_unit=Decimal("12.5"),
                ),
            ),
        ),
        LegacyCoffeeRecipe(
            bundle_code="2302",
            name="Espresso",
            components=(
                LegacyCoffeeRecipeComponent(
                    product_code="missing-ms",
                    quantity_per_unit=Decimal("10"),
                ),
            ),
        ),
    )

    report = migrate_legacy_recipes(
        legacy,
        products=store,
        recipe_repo=repo,
        allow_partial=True,
    )

    assert report.migrated == 1
    assert repo.get("drink-1") is not None
    assert repo.get("drink-2") is None
    assert any("2302" in gap or "missing-ms" in gap for gap in report.gaps)


def test_legacy_document_reader_round_trip() -> None:
    from src.infrastructure.mongodb.coffee_recipes import legacy_coffee_recipe_from_document

    document = {
        "bundle_code": "2301",
        "name": "Latte",
        "components": [
            {
                "product_code": "coffee-1",
                "quantity_per_unit": "12.5",
                "entity_type": "product",
            },
        ],
    }
    legacy = legacy_coffee_recipe_from_document(document)
    assert legacy.bundle_code == "2301"
    assert legacy.components[0].product_code == "coffee-1"
    assert legacy.components[0].entity_type == "product"
