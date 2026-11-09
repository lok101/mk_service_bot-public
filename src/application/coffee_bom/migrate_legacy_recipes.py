from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.product_identity import catalog_codes_of
from src.application.product_identity.ports import DomainProductStore
from src.domain.coffee_bom.models import CoffeeRecipe, CoffeeRecipeComponent

ComponentEntityType = Literal["product", "variant"]


@beartype
@dataclass(frozen=True, slots=True)
class LegacyCoffeeRecipeComponent:
    product_code: str
    quantity_per_unit: Decimal
    entity_type: ComponentEntityType | None = None


@beartype
@dataclass(frozen=True, slots=True)
class LegacyCoffeeRecipe:
    bundle_code: str
    name: str
    components: tuple[LegacyCoffeeRecipeComponent, ...]


@beartype
@dataclass(frozen=True, slots=True)
class LegacyRecipeMigrateReport:
    migrated: int
    gaps: tuple[str, ...]


@beartype
def migrate_legacy_recipes(
    legacy_recipes: tuple[LegacyCoffeeRecipe, ...],
    *,
    products: DomainProductStore,
    recipe_repo: CoffeeRecipeRepository,
    allow_partial: bool = False,
) -> LegacyRecipeMigrateReport:
    gaps: list[str] = []
    pending: list[CoffeeRecipe] = []
    drinks_by_legacy = {
        product.legacy_ms_code: product
        for product in products.list_visible()
        if product.kind == "coffee_drink" and product.legacy_ms_code
    }
    ingredients_by_ms: dict[str, str] = {}
    for product in products.list_visible():
        if product.kind != "coffee_ingredient":
            continue
        for code in catalog_codes_of(product):
            ingredients_by_ms.setdefault(code, product.domain_product_id)

    for legacy in legacy_recipes:
        drink = drinks_by_legacy.get(legacy.bundle_code)
        if drink is None:
            gaps.append(f"bundle {legacy.bundle_code!r}: no coffee_drink with legacy_ms_code")
            continue
        mapped: list[CoffeeRecipeComponent] = []
        recipe_gaps: list[str] = []
        for component in legacy.components:
            ingredient_id = ingredients_by_ms.get(component.product_code)
            if ingredient_id is None:
                recipe_gaps.append(
                    f"bundle {legacy.bundle_code!r}: no coffee_ingredient link for "
                    f"{component.product_code!r}",
                )
                continue
            mapped.append(
                CoffeeRecipeComponent(
                    ingredient_product_id=ingredient_id,
                    quantity_per_unit=component.quantity_per_unit,
                    entity_type=component.entity_type,
                ),
            )
        if recipe_gaps:
            gaps.extend(recipe_gaps)
            continue
        pending.append(
            CoffeeRecipe(
                drink_product_id=drink.domain_product_id,
                components=tuple(mapped),
                name=legacy.name,
            ),
        )

    if gaps and not allow_partial:
        return LegacyRecipeMigrateReport(migrated=0, gaps=tuple(gaps))

    for recipe in pending:
        recipe_repo.upsert(recipe)
    return LegacyRecipeMigrateReport(migrated=len(pending), gaps=tuple(gaps))
