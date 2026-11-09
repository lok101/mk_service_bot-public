from __future__ import annotations

from decimal import Decimal

from beartype import beartype

from src.application.form_submissions.conversions import validated_lines_to_frozen
from src.application.form_submissions.form_quantities import (
    load_product_specs,
    product_titles_from_answers,
)
from src.application.form_submissions.ports import ProductCodeResolver
from src.application.form_submissions.quantity_validation import parse_validated_inventory_lines
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionPurpose,
    FrozenInventoryLine,
)
from src.domain.quantities import QuantityInputMode, mode_from_form_purpose

_WAREHOUSE_MAX_PACKAGES = Decimal("99")


@beartype
def parse_and_build_frozen_inventory_lines(
    *,
    product_code_resolver: ProductCodeResolver,
    form_token_field_name: str,
    answers: tuple[FormAnswer, ...],
    mode_purpose: FormSubmissionPurpose | str,
    quantity_mode: QuantityInputMode | None = None,
    allow_empty: bool | None = None,
    apply_stock_range: bool | None = None,
    allow_zero: bool | None = None,
) -> tuple[FrozenInventoryLine, ...]:
    purpose = str(mode_purpose)
    max_packages: Decimal | None = None
    if quantity_mode is not None:
        mode = quantity_mode
        resolved_allow_empty = True if allow_empty is None else allow_empty
        resolved_apply_stock_range = True if apply_stock_range is None else apply_stock_range
        resolved_allow_zero = True if allow_zero is None else allow_zero
        if purpose == "technician_warehouse_inventory":
            max_packages = _WAREHOUSE_MAX_PACKAGES
    else:
        mode = mode_from_form_purpose(purpose)
        if purpose == "technician_warehouse_inventory":
            resolved_allow_empty = True
            resolved_apply_stock_range = False
            resolved_allow_zero = True
            max_packages = _WAREHOUSE_MAX_PACKAGES
        elif purpose == "loading":
            # LOK-13: explicit zeros required for catalog lines; empty form still blocked.
            resolved_allow_empty = False
            resolved_apply_stock_range = True
            resolved_allow_zero = True
        else:  # revision
            resolved_allow_empty = True
            resolved_apply_stock_range = True
            resolved_allow_zero = True
        if allow_empty is not None:
            resolved_allow_empty = allow_empty
        if apply_stock_range is not None:
            resolved_apply_stock_range = apply_stock_range
        if allow_zero is not None:
            resolved_allow_zero = allow_zero
    excluded_titles = frozenset({form_token_field_name})
    titles = product_titles_from_answers(answers, excluded_titles=excluded_titles)
    product_specs = load_product_specs(product_code_resolver, titles)
    validated = parse_validated_inventory_lines(
        answers,
        excluded_titles=excluded_titles,
        product_specs=product_specs,
        mode=mode,
        allow_empty=resolved_allow_empty,
        apply_stock_range=resolved_apply_stock_range,
        allow_zero=resolved_allow_zero,
        max_packages=max_packages,
    )
    return validated_lines_to_frozen(
        answers,
        validated,
        excluded_titles=excluded_titles,
    )
