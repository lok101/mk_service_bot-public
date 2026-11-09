from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.form_submissions.conversions import (
    frozen_line_to_validated,
    product_spec_to_frozen,
    validated_line_to_frozen,
    validated_lines_to_frozen,
)
from src.application.form_submissions.quantity_validation import ValidatedInventoryLine
from src.domain.form_submission import FormAnswer
from src.domain.product_catalog import ProductSpec, ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.testing.stubs import MappingProductCatalogResolver


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


def test_validated_line_round_trip_preserves_moysklad_fields() -> None:
    line = ValidatedInventoryLine(product_spec=_coffee_spec(), quantity=Decimal("3"))
    frozen = validated_line_to_frozen(line, form_title="Кофе")
    restored = frozen_line_to_validated(frozen)

    assert restored.quantity == Decimal("3")
    assert restored.product_spec.product_code == "coffee-1"
    assert restored.product_spec.pack_size == Decimal("20")
    assert restored.product_spec.moysklad_quantity_factor == Decimal("0.001")


def test_validated_lines_to_frozen_aligns_form_titles_with_answers() -> None:
    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="2"),
    )
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    specs = {"Кофе": resolver.resolve_by_name("Кофе")}
    from src.application.form_submissions.quantity_validation import parse_validated_inventory_lines
    from src.domain.quantities import QuantityInputMode

    lines = parse_validated_inventory_lines(
        answers,
        excluded_titles=frozenset({"Код заявки."}),
        product_specs=specs,
        mode=QuantityInputMode.PACKAGE_COUNT,
        allow_empty=False,
        apply_stock_range=True,
        allow_zero=False,
    )
    frozen = validated_lines_to_frozen(
        answers,
        lines,
        excluded_titles=frozenset({"Код заявки."}),
    )

    assert len(frozen) == 1
    assert frozen[0].form_title == "Кофе"
    assert frozen[0].product_spec.product_code == "coffee-1"


def test_product_spec_to_frozen_copies_processing_fields_only() -> None:
    frozen = product_spec_to_frozen(_coffee_spec())

    assert frozen.product_code == "coffee-1"
    assert frozen.name == "Кофе"
    assert frozen.unit == ProductUnit.GRAM
    assert frozen.pack_size == Decimal("20")


def test_parse_and_build_warehouse_accepts_zero_packages() -> None:
    from src.application.form_submissions.inventory_snapshot import (
        parse_and_build_frozen_inventory_lines,
    )

    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="0"),
    )
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    frozen = parse_and_build_frozen_inventory_lines(
        product_code_resolver=resolver,
        form_token_field_name="Код заявки.",
        answers=answers,
        mode_purpose="technician_warehouse_inventory",
    )
    assert len(frozen) == 1
    assert frozen[0].quantity == Decimal("0")


def test_parse_and_build_loading_accepts_zero() -> None:
    # LOK-13: zeros are explicit catalog answers, not a skip
    from src.application.form_submissions.inventory_snapshot import (
        parse_and_build_frozen_inventory_lines,
    )

    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="0"),
    )
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    frozen = parse_and_build_frozen_inventory_lines(
        product_code_resolver=resolver,
        form_token_field_name="Код заявки.",
        answers=answers,
        mode_purpose="loading",
    )
    assert len(frozen) == 1
    assert frozen[0].quantity == Decimal("0")


def test_warehouse_accepts_99_packages() -> None:
    from src.application.form_submissions.inventory_snapshot import (
        parse_and_build_frozen_inventory_lines,
    )

    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="99"),
    )
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    frozen = parse_and_build_frozen_inventory_lines(
        product_code_resolver=resolver,
        form_token_field_name="Код заявки.",
        answers=answers,
        mode_purpose="technician_warehouse_inventory",
    )
    assert len(frozen) == 1
    assert frozen[0].quantity == Decimal("99")


def test_warehouse_rejects_100_packages() -> None:
    from src.application.form_submissions.inventory_snapshot import (
        parse_and_build_frozen_inventory_lines,
    )
    from src.application.form_submissions.quantity_validation import QuantityValidationError

    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="100"),
    )
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    with pytest.raises(QuantityValidationError, match="99"):
        parse_and_build_frozen_inventory_lines(
            product_code_resolver=resolver,
            form_token_field_name="Код заявки.",
            answers=answers,
            mode_purpose="technician_warehouse_inventory",
        )


def test_loading_large_package_count_not_capped_by_max_packages() -> None:
    # edge: loading has no absolute package cap (catalog min/max None on coffee stub)
    from src.application.form_submissions.inventory_snapshot import (
        parse_and_build_frozen_inventory_lines,
    )

    answers = (
        FormAnswer(title="Код заявки.", value="token"),
        FormAnswer(title="Кофе", value="150"),
    )
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    frozen = parse_and_build_frozen_inventory_lines(
        product_code_resolver=resolver,
        form_token_field_name="Код заявки.",
        answers=answers,
        mode_purpose="loading",
    )
    assert len(frozen) == 1
    assert frozen[0].quantity == Decimal("150")
