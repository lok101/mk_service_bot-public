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


def test_expand_sale_to_ms_codes() -> None:
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


def test_expand_multi_link_uses_first_ms_code() -> None:
    sales = (PeriodSaleLine(product_code="2301", quantity=Decimal("2"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={"drink-1": _LATTE},
        ms_code_by_ingredient_id={"ing-1": "primary-ms", "ing-2": "cup-1"},
    )
    assert isinstance(result, tuple)
    assert result[0].product_code == "primary-ms"
    assert result[0].quantity == Decimal("25")


def test_expand_unresolved_when_ms_link_missing() -> None:
    sales = (PeriodSaleLine(product_code="2301", quantity=Decimal("1"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={"drink-1": _LATTE},
        ms_code_by_ingredient_id={"ing-1": "coffee-1"},
    )
    assert isinstance(result, UnresolvedCoffeeRecipes)
    assert result.bundle_codes == ("2301",)


def test_expand_unresolved_when_recipe_missing() -> None:
    sales = (PeriodSaleLine(product_code="2301", quantity=Decimal("1"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={},
        ms_code_by_ingredient_id={},
    )
    assert isinstance(result, UnresolvedCoffeeRecipes)
    assert result.bundle_codes == ("2301",)


def test_expand_unresolved_when_recipe_empty() -> None:
    sales = (PeriodSaleLine(product_code="2301", quantity=Decimal("1"), occurred_at=_INSIDE),)
    empty = CoffeeRecipe(drink_product_id="drink-1", name="Latte", components=())
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={"2301": "drink-1"},
        recipes_by_drink_id={"drink-1": empty},
        ms_code_by_ingredient_id={},
    )
    assert isinstance(result, UnresolvedCoffeeRecipes)
    assert result.bundle_codes == ("2301",)


def test_expand_unresolved_when_drink_unresolved() -> None:
    sales = (PeriodSaleLine(product_code="9999", quantity=Decimal("1"), occurred_at=_INSIDE),)
    result = expand_coffee_sales(
        sales,
        drink_id_by_sale_code={},
        recipes_by_drink_id={},
        ms_code_by_ingredient_id={},
    )
    assert isinstance(result, UnresolvedCoffeeRecipes)
    assert result.bundle_codes == ("9999",)
