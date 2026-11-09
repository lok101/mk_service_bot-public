from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.coffee_bom.expand import expand_coffee_sales
from src.domain.coffee_bom.models import (
    CoffeeRecipe,
    CoffeeRecipeComponent,
    UnresolvedCoffeeRecipes,
)
from src.domain.inventory_reconciliation.models import PeriodSaleLine

_INSIDE = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_LATTE = CoffeeRecipe(
    drink_product_id="drink-1",
    name="Latte",
    components=(
        CoffeeRecipeComponent(
            ingredient_product_id="ing-1",
            quantity_per_unit=Decimal("12.5"),
        ),
        CoffeeRecipeComponent(
            ingredient_product_id="ing-2",
            quantity_per_unit=Decimal("1"),
        ),
    ),
)


def test_expand_one_bundle_sale_into_components() -> None:
    sales = (PeriodSaleLine(product_code="2301", quantity=Decimal("1"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={"drink-1": _LATTE},
        ms_code_by_ingredient_id={"ing-1": "coffee-1", "ing-2": "cup-1"},
    )
    assert isinstance(result, tuple)
    by_code = {line.product_code: line.quantity for line in result}
    assert by_code == {"coffee-1": Decimal("12.5"), "cup-1": Decimal("1")}


def test_expand_three_latte_sales_multiplies_component_qty() -> None:
    sales = (PeriodSaleLine(product_code="2301", quantity=Decimal("3"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={"drink-1": _LATTE},
        ms_code_by_ingredient_id={"ing-1": "coffee-1", "ing-2": "cup-1"},
    )
    assert isinstance(result, tuple)
    by_code = {line.product_code: line.quantity for line in result}
    assert by_code["coffee-1"] == Decimal("37.5")
    assert by_code["cup-1"] == Decimal("3")


def test_expand_returns_unresolved_when_bundle_missing() -> None:
    sales = (PeriodSaleLine(product_code="9999", quantity=Decimal("1"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={},
        recipes_by_drink_id={},
        ms_code_by_ingredient_id={},
    )
    assert isinstance(result, UnresolvedCoffeeRecipes)
    assert result.bundle_codes == ("9999",)


def test_expand_empty_sales_returns_empty_tuple() -> None:
    result = expand_coffee_sales(
        (),
        drink_id_by_sale_code={},
        recipes_by_drink_id={},
        ms_code_by_ingredient_id={},
    )
    assert result == ()


def test_expand_unresolved_when_any_bundle_missing() -> None:
    sales = (
        PeriodSaleLine(product_code="2301", quantity=Decimal("1"), occurred_at=_INSIDE),
        PeriodSaleLine(product_code="9999", quantity=Decimal("1"), occurred_at=_INSIDE),
    )
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={"drink-1": _LATTE},
        ms_code_by_ingredient_id={"ing-1": "coffee-1", "ing-2": "cup-1"},
    )
    assert isinstance(result, UnresolvedCoffeeRecipes)
    assert result.bundle_codes == ("9999",)
