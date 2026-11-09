from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.coffee_bom.expand_sales import (
    expand_coffee_sales_via_domain,
    first_ms_code_for_ingredient,
    resolve_coffee_drink_id_by_sale_code,
)
from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.product_identity.ports import DomainProductStore
from src.domain.coffee_bom.models import UnresolvedCoffeeRecipes
from src.domain.inventory_reconciliation.models import PeriodSaleLine
from src.domain.inventory_reconciliation.snapshot import FrozenSalesLine
from src.domain.machine_sales import MachineSale


@beartype
@dataclass(frozen=True, slots=True)
class PreparedCoffeeSales:
    period_sales: tuple[PeriodSaleLine, ...]
    frozen_sales: tuple[FrozenSalesLine, ...]
    bom_coverage_ok: bool
    unresolved_bundle_codes: tuple[str, ...]


@beartype
def prepare_coffee_sales_for_reconciliation(
    machine_sales: tuple[MachineSale, ...],
    *,
    recipe_repo: CoffeeRecipeRepository,
    products: DomainProductStore,
) -> PreparedCoffeeSales:
    coffee_sales = tuple(sale for sale in machine_sales if sale.sale_kind == "coffee")
    if not coffee_sales:
        return PreparedCoffeeSales(
            period_sales=(),
            frozen_sales=(),
            bom_coverage_ok=True,
            unresolved_bundle_codes=(),
        )

    bundle_sales = tuple(
        PeriodSaleLine(
            product_code=sale.product_code,
            quantity=sale.quantity,
            occurred_at=sale.occurred_at,
        )
        for sale in coffee_sales
    )
    expanded = expand_coffee_sales_via_domain(
        bundle_sales,
        recipe_repo=recipe_repo,
        products=products,
    )
    if isinstance(expanded, UnresolvedCoffeeRecipes):
        return PreparedCoffeeSales(
            period_sales=(),
            frozen_sales=(),
            bom_coverage_ok=False,
            unresolved_bundle_codes=expanded.bundle_codes,
        )

    frozen_sales: list[FrozenSalesLine] = []
    for sale in coffee_sales:
        drink_id = resolve_coffee_drink_id_by_sale_code(sale.product_code, products=products)
        if drink_id is None:
            continue
        recipe = recipe_repo.get(drink_id)
        if recipe is None:
            continue
        for component in recipe.components:
            ms_code = first_ms_code_for_ingredient(
                component.ingredient_product_id,
                products=products,
            )
            if ms_code is None:
                continue
            quantity = sale.quantity * component.quantity_per_unit
            frozen_sales.append(
                FrozenSalesLine(
                    product_code=ms_code,
                    quantity=quantity,
                    occurred_at=sale.occurred_at,
                    source_id=sale.source_id,
                ),
            )

    return PreparedCoffeeSales(
        period_sales=expanded,
        frozen_sales=tuple(frozen_sales),
        bom_coverage_ok=True,
        unresolved_bundle_codes=(),
    )
