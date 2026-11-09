from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from src.application.form_submissions.quantity_validation import (
    QuantityValidationError,
    SuspiciousUnitMismatchError,
    parse_raw_quantity,
    parse_validated_inventory_lines,
    validate_quantity_for_mode,
)
from src.domain.form_submission import FormAnswer
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)
from src.domain.quantities import QuantityInputMode


def _coffee_spec(
    *,
    min_stock: Decimal | None = Decimal("100"),
    max_stock: Decimal | None = Decimal("200"),
) -> ProductSpec:
    unit = ProductUnit.GRAM
    return ProductSpec(
        product_code="coffee-1",
        name="Кофе",
        unit=unit,
        pack_size=Decimal("20"),
        min_stock=min_stock,
        max_stock=max_stock,
        allow_fraction=True,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )


def test_parse_raw_quantity_parses_decimal_with_comma() -> None:
    q = parse_raw_quantity(value="2,5", product_name="Кофе")
    assert q == Decimal("2.5")


def test_parse_raw_quantity_rejects_empty() -> None:
    with pytest.raises(QuantityValidationError, match="Invalid quantity"):
        parse_raw_quantity(value="   ", product_name="Кофе")


def test_validate_revision_piece_requires_integer() -> None:
    unit = ProductUnit.PIECE
    spec = ProductSpec(
        product_code="p1",
        name="Стакан",
        unit=unit,
        pack_size=Decimal("10"),
        min_stock=None,
        max_stock=None,
        allow_fraction=False,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )

    with pytest.raises(QuantityValidationError, match="must be an integer"):
        validate_quantity_for_mode(
            amount=Decimal("2.5"),
            spec=spec,
            mode=QuantityInputMode.BASE_STOCK,
            apply_stock_range=True,
            allow_zero=True,
        )


def test_validate_loading_packages_requires_integer() -> None:
    unit = ProductUnit.GRAM
    spec = ProductSpec(
        product_code="p1",
        name="Кофе",
        unit=unit,
        pack_size=Decimal("20"),
        min_stock=Decimal("100"),
        max_stock=Decimal("200"),
        allow_fraction=True,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )

    with pytest.raises(QuantityValidationError, match="must be an integer"):
        validate_quantity_for_mode(
            amount=Decimal("3.5"),
            spec=spec,
            mode=QuantityInputMode.PACKAGE_COUNT,
            apply_stock_range=True,
            allow_zero=False,
        )


def test_suspicious_unit_mismatch_loading_packages_grams_entered() -> None:
    # pack_size=20g per package, allowed base range 100..200g.
    # If user entered 160 (grams) into packages field:
    # - correct interpretation: 160 packages => 3200g (out of range)
    # - alternative interpretation: 160g => 8 packages (in range)
    unit = ProductUnit.GRAM
    spec = ProductSpec(
        product_code="p1",
        name="Кофе",
        unit=unit,
        pack_size=Decimal("20"),
        min_stock=Decimal("100"),
        max_stock=Decimal("200"),
        allow_fraction=True,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )

    with pytest.raises(SuspiciousUnitMismatchError, match="expected packages"):
        validate_quantity_for_mode(
            amount=Decimal("160"),
            spec=spec,
            mode=QuantityInputMode.PACKAGE_COUNT,
            apply_stock_range=True,
            allow_zero=False,
        )


def test_suspicious_unit_mismatch_revision_stock_packages_entered() -> None:
    # pack_size=20g per package, allowed base range 100..200g.
    # If user entered 8 (packages) into grams field:
    # - correct interpretation: 8g (out of range)
    # - alternative interpretation: 8 packages => 160g (in range)
    unit = ProductUnit.GRAM
    spec = ProductSpec(
        product_code="p1",
        name="Кофе",
        unit=unit,
        pack_size=Decimal("20"),
        min_stock=Decimal("100"),
        max_stock=Decimal("200"),
        allow_fraction=True,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )

    with pytest.raises(SuspiciousUnitMismatchError, match="fits as packages"):
        validate_quantity_for_mode(
            amount=Decimal("8"),
            spec=spec,
            mode=QuantityInputMode.BASE_STOCK,
            apply_stock_range=True,
            allow_zero=True,
        )


def test_parse_validated_inventory_lines_filters_token_and_validates() -> None:
    coffee_unit = ProductUnit.GRAM
    piece_unit = ProductUnit.PIECE
    catalog = {
        "Кофе": ProductSpec(
            product_code="p1",
            name="Кофе",
            unit=coffee_unit,
            pack_size=Decimal("20"),
            min_stock=None,
            max_stock=None,
            allow_fraction=True,
            moysklad_quantity_factor=default_moysklad_quantity_factor(coffee_unit),
        ),
        "Стакан": ProductSpec(
            product_code="p2",
            name="Стакан",
            unit=piece_unit,
            pack_size=Decimal("1"),
            min_stock=None,
            max_stock=None,
            allow_fraction=False,
            moysklad_quantity_factor=default_moysklad_quantity_factor(piece_unit),
        ),
    }

    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="12,5"),
        FormAnswer(title="Стакан", value="2"),
    )

    lines = parse_validated_inventory_lines(
        answers,
        excluded_titles=frozenset({"Код заявки."}),
        product_specs=catalog,
        mode=QuantityInputMode.BASE_STOCK,
        allow_empty=True,
        apply_stock_range=True,
        allow_zero=True,
    )

    assert [line.product_spec.name for line in lines] == ["Кофе", "Стакан"]
    assert lines[0].quantity == Decimal("12.5")
    assert lines[1].quantity == Decimal("2")


def test_parse_validated_inventory_lines_allows_empty_revision() -> None:
    answers = (FormAnswer(title="Код заявки.", value="token"),)

    lines = parse_validated_inventory_lines(
        answers,
        excluded_titles=frozenset({"Код заявки."}),
        product_specs={},
        mode=QuantityInputMode.BASE_STOCK,
        allow_empty=True,
        apply_stock_range=True,
        allow_zero=True,
    )

    assert lines == []


def test_parse_validated_inventory_lines_rejects_empty_loading() -> None:
    answers = (FormAnswer(title="Код заявки.", value="token"),)

    with pytest.raises(QuantityValidationError, match="no product lines"):
        parse_validated_inventory_lines(
            answers,
            excluded_titles=frozenset({"Код заявки."}),
            product_specs={},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=False,
            apply_stock_range=True,
            allow_zero=False,
        )


def test_warehouse_inventory_allows_empty_and_skips_stock_range() -> None:
    assert (
        parse_validated_inventory_lines(
            (),
            excluded_titles=frozenset(),
            product_specs={},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=True,
            apply_stock_range=False,
            allow_zero=True,
        )
        == []
    )
    lines = parse_validated_inventory_lines(
        (FormAnswer(title="Кофе", value="50"),),
        excluded_titles=frozenset(),
        product_specs={"Кофе": _coffee_spec()},
        mode=QuantityInputMode.PACKAGE_COUNT,
        allow_empty=True,
        apply_stock_range=False,
        allow_zero=True,
    )
    assert len(lines) == 1
    assert lines[0].quantity == Decimal("50")


def test_loading_packages_empty_form_rejected() -> None:
    with pytest.raises(QuantityValidationError, match="no product lines"):
        parse_validated_inventory_lines(
            (),
            excluded_titles=frozenset(),
            product_specs={},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=False,
            apply_stock_range=True,
            allow_zero=False,
        )


def test_loading_packages_still_applies_suspicious_mismatch() -> None:
    with pytest.raises(SuspiciousUnitMismatchError):
        parse_validated_inventory_lines(
            (FormAnswer(title="Кофе", value="160"),),
            excluded_titles=frozenset(),
            product_specs={"Кофе": _coffee_spec()},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=False,
            apply_stock_range=True,
            allow_zero=False,
        )


def test_warehouse_zero_packages_accepted_with_pack_size() -> None:
    # happy: PACKAGE_COUNT + allow_zero, amount 0, pack_size set
    lines = parse_validated_inventory_lines(
        (FormAnswer(title="Кофе", value="0"),),
        excluded_titles=frozenset(),
        product_specs={"Кофе": _coffee_spec()},
        mode=QuantityInputMode.PACKAGE_COUNT,
        allow_empty=True,
        apply_stock_range=False,
        allow_zero=True,
    )
    assert len(lines) == 1
    assert lines[0].quantity == Decimal("0")


def test_revision_zero_skips_stock_range() -> None:
    # happy: BASE_STOCK + allow_zero; min/max would reject nonzero out of range
    lines = parse_validated_inventory_lines(
        (FormAnswer(title="Кофе", value="0"),),
        excluded_titles=frozenset(),
        product_specs={"Кофе": _coffee_spec()},
        mode=QuantityInputMode.BASE_STOCK,
        allow_empty=True,
        apply_stock_range=True,
        allow_zero=True,
    )
    assert len(lines) == 1
    assert lines[0].quantity == Decimal("0")


def test_allow_zero_accepts_comma_decimal_zero() -> None:
    # happy: "0,0" → Decimal 0
    lines = parse_validated_inventory_lines(
        (FormAnswer(title="Кофе", value="0,0"),),
        excluded_titles=frozenset(),
        product_specs={"Кофе": _coffee_spec()},
        mode=QuantityInputMode.PACKAGE_COUNT,
        allow_empty=True,
        apply_stock_range=False,
        allow_zero=True,
    )
    assert lines[0].quantity == Decimal("0")


def test_loading_zero_still_rejected() -> None:
    # error
    with pytest.raises(QuantityValidationError, match="must be positive"):
        parse_validated_inventory_lines(
            (FormAnswer(title="Кофе", value="0"),),
            excluded_titles=frozenset(),
            product_specs={"Кофе": _coffee_spec()},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=False,
            apply_stock_range=True,
            allow_zero=False,
        )


def test_negative_rejected_even_with_allow_zero() -> None:
    # error
    with pytest.raises(QuantityValidationError, match="must be positive|negative|got -"):
        validate_quantity_for_mode(
            amount=Decimal("-1"),
            spec=_coffee_spec(),
            mode=QuantityInputMode.PACKAGE_COUNT,
            apply_stock_range=False,
            allow_zero=True,
        )


def test_warehouse_zero_without_pack_size_rejected() -> None:
    # error: mode-check pack_size remains
    spec = replace(_coffee_spec(), pack_size=None)
    with pytest.raises(QuantityValidationError, match="[Pp]ack size"):
        parse_validated_inventory_lines(
            (FormAnswer(title="Кофе", value="0"),),
            excluded_titles=frozenset(),
            product_specs={"Кофе": spec},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=True,
            apply_stock_range=False,
            allow_zero=True,
        )


def test_revision_nonzero_still_applies_stock_range() -> None:
    # edge: out-of-range nonzero still fails (suspicious or range)
    with pytest.raises((QuantityValidationError, SuspiciousUnitMismatchError)):
        parse_validated_inventory_lines(
            (FormAnswer(title="Кофе", value="8"),),
            excluded_titles=frozenset(),
            product_specs={"Кофе": _coffee_spec()},
            mode=QuantityInputMode.BASE_STOCK,
            allow_empty=True,
            apply_stock_range=True,
            allow_zero=True,
        )


def test_max_packages_accepts_99_and_zero() -> None:
    # happy: warehouse-style cap inclusive 99; zero with allow_zero
    for value in ("99", "0"):
        lines = parse_validated_inventory_lines(
            (FormAnswer(title="Кофе", value=value),),
            excluded_titles=frozenset(),
            product_specs={"Кофе": _coffee_spec()},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=True,
            apply_stock_range=False,
            allow_zero=True,
            max_packages=Decimal("99"),
        )
        assert len(lines) == 1
        assert lines[0].quantity == Decimal(value)


def test_max_packages_accepts_98() -> None:
    # edge
    lines = parse_validated_inventory_lines(
        (FormAnswer(title="Кофе", value="98"),),
        excluded_titles=frozenset(),
        product_specs={"Кофе": _coffee_spec()},
        mode=QuantityInputMode.PACKAGE_COUNT,
        allow_empty=True,
        apply_stock_range=False,
        allow_zero=True,
        max_packages=Decimal("99"),
    )
    assert lines[0].quantity == Decimal("98")


def test_max_packages_none_allows_large_package_count() -> None:
    # edge: loading-style — absolute cap off; skip catalog range
    lines = parse_validated_inventory_lines(
        (FormAnswer(title="Кофе", value="150"),),
        excluded_titles=frozenset(),
        product_specs={"Кофе": _coffee_spec(min_stock=None, max_stock=None)},
        mode=QuantityInputMode.PACKAGE_COUNT,
        allow_empty=False,
        apply_stock_range=True,
        allow_zero=False,
        max_packages=None,
    )
    assert lines[0].quantity == Decimal("150")


def test_max_packages_rejects_100() -> None:
    # error
    with pytest.raises(QuantityValidationError, match="99"):
        parse_validated_inventory_lines(
            (FormAnswer(title="Кофе", value="100"),),
            excluded_titles=frozenset(),
            product_specs={"Кофе": _coffee_spec()},
            mode=QuantityInputMode.PACKAGE_COUNT,
            allow_empty=True,
            apply_stock_range=False,
            allow_zero=True,
            max_packages=Decimal("99"),
        )
