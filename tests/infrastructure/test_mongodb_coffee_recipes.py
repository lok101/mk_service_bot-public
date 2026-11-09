from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import mongomock

from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.infrastructure.mongodb.coffee_recipes import MongoCoffeeRecipeRepository


@dataclass
class _IndexRecordingCollection:
    index_calls: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str:
        self.index_calls.append((keys, kwargs))
        return "coffee_recipes_drink_product_id_unique"

    def replace_one(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def find_one(self, *args: Any, **kwargs: Any) -> None:
        return None

    def find(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


def test_upsert_and_get_by_drink_ids() -> None:
    collection = mongomock.MongoClient().db.coffee_recipes
    repo = MongoCoffeeRecipeRepository.from_collection(collection)
    recipe = CoffeeRecipe(
        drink_product_id="drink-1",
        name="Latte",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="ing-1",
                quantity_per_unit=Decimal("12.5"),
            ),
        ),
    )
    repo.upsert(recipe)
    loaded = repo.get_by_drink_ids(frozenset({"drink-1"}))
    assert loaded["drink-1"].name == "Latte"


def test_upsert_persists_legacy_bundle_code() -> None:
    collection = mongomock.MongoClient().db.coffee_recipes
    repo = MongoCoffeeRecipeRepository.from_collection(collection)
    recipe = CoffeeRecipe(
        drink_product_id="drink-1",
        name="Latte",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="ing-1",
                quantity_per_unit=Decimal("1"),
            ),
        ),
    )
    repo.upsert(recipe, legacy_bundle_code="2301")
    stored = collection.find_one({"drink_product_id": "drink-1"})
    assert stored is not None
    assert stored["bundle_code"] == "2301"


def test_get_returns_none_for_missing_drink() -> None:
    collection = mongomock.MongoClient().db.coffee_recipes
    repo = MongoCoffeeRecipeRepository.from_collection(collection)

    assert repo.get("missing") is None


def test_upsert_round_trips_component_entity_type() -> None:
    collection = mongomock.MongoClient().db.coffee_recipes
    repo = MongoCoffeeRecipeRepository.from_collection(collection)
    recipe = CoffeeRecipe(
        drink_product_id="drink-1",
        name="Latte",
        components=(
            CoffeeRecipeComponent(
                ingredient_product_id="ing-1",
                quantity_per_unit=Decimal("12.5"),
                entity_type="product",
            ),
        ),
    )
    repo.upsert(recipe)
    loaded = repo.get("drink-1")
    assert loaded is not None
    assert loaded.components[0].entity_type == "product"


def test_ensure_indexes_uses_partial_unique_on_drink_product_id() -> None:
    collection = _IndexRecordingCollection()
    MongoCoffeeRecipeRepository(_collection=collection).ensure_indexes()

    assert len(collection.index_calls) == 1
    keys, kwargs = collection.index_calls[0]
    assert keys == [("drink_product_id", 1)]
    assert kwargs["unique"] is True
    assert kwargs["name"] == "coffee_recipes_drink_product_id_unique"
    assert kwargs["partialFilterExpression"] == {"drink_product_id": {"$type": "string"}}


def test_list_drink_ids_returns_sorted_ids() -> None:
    collection = mongomock.MongoClient().db.coffee_recipes
    repo = MongoCoffeeRecipeRepository.from_collection(collection)
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
    repo.upsert(
        CoffeeRecipe(
            drink_product_id="drink-1",
            name="Latte",
            components=(
                CoffeeRecipeComponent(
                    ingredient_product_id="ing-1",
                    quantity_per_unit=Decimal("12.5"),
                ),
            ),
        ),
    )

    assert repo.list_drink_ids() == ("drink-1", "drink-2")
