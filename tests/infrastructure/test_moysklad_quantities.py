from __future__ import annotations

from decimal import Decimal

from src.application.form_submissions.quantity_validation import ValidatedInventoryLine
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)
from src.domain.quantities import QuantityInputMode
from src.infrastructure.integrations.moysklad.quantities import (
    catalog_base_quantity,
    from_moysklad_quantity,
    to_moysklad_quantity,
    validated_lines_to_moysklad_positions,
)


def _coffee_spec() -> ProductSpec:
    unit = ProductUnit.GRAM
    return ProductSpec(
        product_code="coffee-1",
        name="Кофе",
        unit=unit,
        pack_size=Decimal("20"),
        min_stock=None,
        max_stock=None,
        allow_fraction=True,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )


def test_to_moysklad_quantity_converts_grams_to_kilograms() -> None:
    spec = _coffee_spec()

    assert to_moysklad_quantity(spec, Decimal("350")) == Decimal("0.35")


def test_from_moysklad_quantity_converts_kilograms_to_grams() -> None:
    spec = _coffee_spec()

    assert from_moysklad_quantity(spec, Decimal("0.35")) == Decimal("350")


def test_to_moysklad_quantity_keeps_pieces_unchanged() -> None:
    unit = ProductUnit.PIECE
    spec = ProductSpec(
        product_code="cup-1",
        name="Стакан",
        unit=unit,
        pack_size=Decimal("1"),
        min_stock=None,
        max_stock=None,
        allow_fraction=False,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )

    assert to_moysklad_quantity(spec, Decimal("5")) == Decimal("5")


def test_catalog_base_quantity_multiplies_loading_packages_by_pack_size() -> None:
    line = ValidatedInventoryLine(
        product_spec=_coffee_spec(),
        quantity=Decimal("3"),
    )

    assert catalog_base_quantity(line, QuantityInputMode.PACKAGE_COUNT) == Decimal("60")


def test_validated_lines_to_moysklad_positions_applies_conversion() -> None:
    lines = [
        ValidatedInventoryLine(
            product_spec=_coffee_spec(),
            quantity=Decimal("3000"),
        ),
    ]

    positions = validated_lines_to_moysklad_positions(
        lines,
        mode=QuantityInputMode.BASE_STOCK,
    )

    assert len(positions) == 1
    assert positions[0].product_code == "coffee-1"
    assert positions[0].quantity == 3
