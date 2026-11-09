from __future__ import annotations

from collections.abc import Mapping

from beartype import beartype

from src.domain.coffee_bom.models import CoffeeRecipe, UnresolvedCoffeeRecipes
from src.domain.inventory_reconciliation.models import PeriodSaleLine


@beartype
def expand_coffee_sales(
    sales: tuple[PeriodSaleLine, ...],
    *,
    drink_id_by_sale_code: Mapping[str, str],
    recipes_by_drink_id: Mapping[str, CoffeeRecipe],
    ms_code_by_ingredient_id: Mapping[str, str],
) -> tuple[PeriodSaleLine, ...] | UnresolvedCoffeeRecipes:
    missing: set[str] = set()
    for sale in sales:
        drink_id = drink_id_by_sale_code.get(sale.product_code)
        if drink_id is None:
            missing.add(sale.product_code)
            continue
        recipe = recipes_by_drink_id.get(drink_id)
        if recipe is None or not recipe.components:
            missing.add(sale.product_code)
            continue
        for component in recipe.components:
            if component.ingredient_product_id not in ms_code_by_ingredient_id:
                missing.add(sale.product_code)
                break
    if missing:
        return UnresolvedCoffeeRecipes(bundle_codes=tuple(sorted(missing)))

    expanded: list[PeriodSaleLine] = []
    for sale in sales:
        drink_id = drink_id_by_sale_code[sale.product_code]
        recipe = recipes_by_drink_id[drink_id]
        for component in recipe.components:
            ms_code = ms_code_by_ingredient_id[component.ingredient_product_id]
            expanded.append(
                PeriodSaleLine(
                    product_code=ms_code,
                    quantity=sale.quantity * component.quantity_per_unit,
                    occurred_at=sale.occurred_at,
                ),
            )
    return tuple(expanded)
