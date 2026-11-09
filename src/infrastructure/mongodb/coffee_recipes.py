from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.application.coffee_bom.migrate_legacy_recipes import (
    LegacyCoffeeRecipe,
    LegacyCoffeeRecipeComponent,
)
from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.config.mongodb import MongoSettings
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class CoffeeRecipesCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        projection: dict[str, int] | None = None,
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _decimal_to_str(value: Decimal) -> str:
    return format(value, "f")


@beartype
def _decimal_from_document(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("quantity_per_unit must be str or Decimal")


@beartype
def _component_to_document(component: CoffeeRecipeComponent) -> dict[str, Any]:
    document: dict[str, Any] = {
        "ingredient_product_id": component.ingredient_product_id,
        "quantity_per_unit": _decimal_to_str(component.quantity_per_unit),
    }
    if component.entity_type is not None:
        document["entity_type"] = component.entity_type
    return document


@beartype
def _component_from_document(document: dict[str, Any]) -> CoffeeRecipeComponent:
    ingredient_product_id = document.get("ingredient_product_id")
    quantity_per_unit = document.get("quantity_per_unit")
    entity_type = document.get("entity_type")
    if not isinstance(ingredient_product_id, str):
        raise ValueError("component.ingredient_product_id must be a string")
    if entity_type is not None and entity_type not in {"product", "variant"}:
        raise ValueError("component.entity_type must be product, variant, or absent")
    return CoffeeRecipeComponent(
        ingredient_product_id=ingredient_product_id,
        quantity_per_unit=_decimal_from_document(quantity_per_unit),
        entity_type=entity_type,
    )


@beartype
def coffee_recipe_to_document(
    recipe: CoffeeRecipe,
    *,
    legacy_bundle_code: str | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "drink_product_id": recipe.drink_product_id,
        "components": [_component_to_document(component) for component in recipe.components],
    }
    if recipe.name is not None:
        document["name"] = recipe.name
    if legacy_bundle_code is not None:
        document["bundle_code"] = legacy_bundle_code
    return document


@beartype
def coffee_recipe_from_document(document: dict[str, Any]) -> CoffeeRecipe:
    drink_product_id = document.get("drink_product_id")
    name = document.get("name")
    components = document.get("components")
    if not isinstance(drink_product_id, str) or not isinstance(components, list):
        raise ValueError("Coffee recipe document has invalid shape")
    if name is not None and not isinstance(name, str):
        raise ValueError("Coffee recipe document name must be str or absent")
    return CoffeeRecipe(
        drink_product_id=drink_product_id,
        name=name,
        components=tuple(_component_from_document(component) for component in components),
    )


@beartype
def legacy_coffee_recipe_from_document(document: dict[str, Any]) -> LegacyCoffeeRecipe:
    bundle_code = document.get("bundle_code")
    name = document.get("name")
    components = document.get("components")
    if (
        not isinstance(bundle_code, str)
        or not isinstance(name, str)
        or not isinstance(components, list)
    ):
        raise ValueError("Legacy coffee recipe document has invalid shape")
    mapped: list[LegacyCoffeeRecipeComponent] = []
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("Legacy component must be a dict")
        product_code = component.get("product_code")
        quantity_per_unit = component.get("quantity_per_unit")
        entity_type = component.get("entity_type")
        if not isinstance(product_code, str):
            raise ValueError("legacy component.product_code must be a string")
        if entity_type is not None and entity_type not in {"product", "variant"}:
            raise ValueError("legacy component.entity_type must be product, variant, or absent")
        mapped.append(
            LegacyCoffeeRecipeComponent(
                product_code=product_code,
                quantity_per_unit=_decimal_from_document(quantity_per_unit),
                entity_type=entity_type,
            ),
        )
    return LegacyCoffeeRecipe(
        bundle_code=bundle_code,
        name=name,
        components=tuple(mapped),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoCoffeeRecipeRepository(CoffeeRecipeRepository):
    _collection: CoffeeRecipesCollection

    @classmethod
    @beartype
    def from_collection(cls, collection: CoffeeRecipesCollection) -> MongoCoffeeRecipeRepository:
        repo = cls(_collection=collection)
        repo.ensure_indexes()
        return repo

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoCoffeeRecipeRepository:
        collection = resolve_collection(
            settings,
            collection_name=settings.coffee_recipes_collection,
            owner="MongoCoffeeRecipeRepository",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        # Legacy docs keyed by bundle_code omit drink_product_id; a plain unique
        # index treats missing/null as one value and fails index build in prod.
        self._collection.create_index(
            [("drink_product_id", ASCENDING)],
            unique=True,
            name="coffee_recipes_drink_product_id_unique",
            partialFilterExpression={"drink_product_id": {"$type": "string"}},
        )

    @beartype
    def get_by_drink_ids(self, drink_ids: frozenset[str]) -> dict[str, CoffeeRecipe]:
        if not drink_ids:
            return {}
        cursor = self._collection.find({"drink_product_id": {"$in": list(drink_ids)}})
        return {
            document["drink_product_id"]: coffee_recipe_from_document(document)
            for document in cursor
            if isinstance(document.get("drink_product_id"), str)
        }

    @beartype
    def upsert(self, recipe: CoffeeRecipe, *, legacy_bundle_code: str | None = None) -> None:
        document = coffee_recipe_to_document(
            recipe,
            legacy_bundle_code=legacy_bundle_code,
        )
        self._collection.replace_one(
            {"drink_product_id": recipe.drink_product_id},
            document,
            upsert=True,
        )

    @beartype
    def get(self, drink_product_id: str) -> CoffeeRecipe | None:
        document = self._collection.find_one({"drink_product_id": drink_product_id})
        if document is None:
            return None
        return coffee_recipe_from_document(document)

    @beartype
    def list_drink_ids(self) -> tuple[str, ...]:
        cursor = self._collection.find({}, projection={"drink_product_id": 1})
        ids = [
            document["drink_product_id"]
            for document in cursor
            if isinstance(document.get("drink_product_id"), str)
        ]
        return tuple(sorted(ids))

    @beartype
    def list_legacy_recipes(self) -> tuple[LegacyCoffeeRecipe, ...]:
        cursor = self._collection.find({"bundle_code": {"$exists": True}})
        recipes: list[LegacyCoffeeRecipe] = []
        for document in cursor:
            if isinstance(document.get("bundle_code"), str):
                recipes.append(legacy_coffee_recipe_from_document(document))
        return tuple(recipes)
