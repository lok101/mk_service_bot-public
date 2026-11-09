from __future__ import annotations

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.product_identity import catalog_codes_of
from src.application.product_identity.ports import DomainProductStore
from src.domain.coffee_bom.expand import expand_coffee_sales
from src.domain.coffee_bom.models import CoffeeRecipe, UnresolvedCoffeeRecipes
from src.domain.inventory_reconciliation.models import PeriodSaleLine


@beartype
def resolve_coffee_drink_id_by_sale_code(
    sale_code: str,
    *,
    products: DomainProductStore,
) -> str | None:
    product = products.get_by_catalog_code(sale_code)
    if product is None or product.kind != "coffee_drink":
        return None
    return product.domain_product_id


@beartype
def first_ms_code_for_ingredient(
    ingredient_product_id: str,
    *,
    products: DomainProductStore,
) -> str | None:
    product = products.get(ingredient_product_id)
    if product is None or product.kind != "coffee_ingredient":
        return None
    codes = catalog_codes_of(product)
    if not codes:
        return None
    return codes[0]


@beartype
def expand_coffee_sales_via_domain(
    sales: tuple[PeriodSaleLine, ...],
    *,
    recipe_repo: CoffeeRecipeRepository,
    products: DomainProductStore,
) -> tuple[PeriodSaleLine, ...] | UnresolvedCoffeeRecipes:
    if not sales:
        return ()

    drink_id_by_sale_code: dict[str, str] = {}
    drink_ids: set[str] = set()
    for sale in sales:
        drink_id = resolve_coffee_drink_id_by_sale_code(sale.product_code, products=products)
        if drink_id is None:
            continue
        drink_id_by_sale_code[sale.product_code] = drink_id
        drink_ids.add(drink_id)

    recipes_by_drink_id = recipe_repo.get_by_drink_ids(frozenset(drink_ids))
    ms_code_by_ingredient_id: dict[str, str] = {}
    for recipe in recipes_by_drink_id.values():
        for component in recipe.components:
            if component.ingredient_product_id in ms_code_by_ingredient_id:
                continue
            ms_code = first_ms_code_for_ingredient(
                component.ingredient_product_id,
                products=products,
            )
            if ms_code is not None:
                ms_code_by_ingredient_id[component.ingredient_product_id] = ms_code

    return expand_coffee_sales(
        sales,
        drink_id_by_sale_code=drink_id_by_sale_code,
        recipes_by_drink_id=recipes_by_drink_id,
        ms_code_by_ingredient_id=ms_code_by_ingredient_id,
    )


@beartype
def recipe_ms_components(
    recipe: CoffeeRecipe,
    *,
    products: DomainProductStore,
) -> tuple[tuple[str, object], ...] | None:
    """Return (ms_code, quantity_per_unit) pairs, or None if any link missing."""
    lines: list[tuple[str, object]] = []
    for component in recipe.components:
        ms_code = first_ms_code_for_ingredient(
            component.ingredient_product_id,
            products=products,
        )
        if ms_code is None:
            return None
        lines.append((ms_code, component.quantity_per_unit))
    return tuple(lines)
