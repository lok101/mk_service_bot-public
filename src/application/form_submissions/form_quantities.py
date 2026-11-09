from __future__ import annotations

from beartype import beartype

from src.application.form_submissions.outbox_errors import (
    FormQuantityValidationError,
    UnknownProductNamesError,
)
from src.application.form_submissions.ports import ProductCodeResolver
from src.application.form_submissions.quantity_validation import (
    QuantityValidationError,
    ValidatedInventoryLine,
    parse_validated_inventory_lines,
)
from src.application.shared.product_title import product_name_for_lookup
from src.domain.form_submission import FormAnswer
from src.domain.product_catalog import ProductSpec
from src.domain.quantities import QuantityInputMode


@beartype
def product_titles_from_answers(
    answers: tuple[FormAnswer, ...],
    *,
    excluded_titles: frozenset[str],
) -> tuple[str, ...]:
    titles: list[str] = []
    seen: set[str] = set()
    for answer in answers:
        title = answer.title.strip()
        if not title or title in excluded_titles or title in seen:
            continue
        seen.add(title)
        titles.append(title)
    return tuple(titles)


@beartype
def load_product_specs(
    resolver: ProductCodeResolver,
    titles: tuple[str, ...],
) -> dict[str, ProductSpec]:
    specs, unknown = load_product_specs_collecting_unknown(resolver, titles)
    if unknown:
        raise ValueError(f"Product spec not found for name {unknown[0]!r}")
    return specs


@beartype
def load_product_specs_collecting_unknown(
    resolver: ProductCodeResolver,
    titles: tuple[str, ...],
) -> tuple[dict[str, ProductSpec], tuple[str, ...]]:
    specs: dict[str, ProductSpec] = {}
    unknown: list[str] = []
    for title in titles:
        lookup_name = product_name_for_lookup(title)
        try:
            specs[title] = resolver.resolve_by_name(lookup_name)
        except ValueError:
            unknown.append(title)
    return specs, tuple(sorted(set(unknown)))


@beartype
def parse_inventory_form_lines(
    answers: tuple[FormAnswer, ...],
    *,
    resolver: ProductCodeResolver,
    excluded_titles: frozenset[str],
    mode: QuantityInputMode,
) -> list[ValidatedInventoryLine]:
    titles = product_titles_from_answers(answers, excluded_titles=excluded_titles)
    product_specs, unknown = load_product_specs_collecting_unknown(resolver, titles)
    if unknown:
        raise UnknownProductNamesError(unknown)

    try:
        return parse_validated_inventory_lines(
            answers,
            excluded_titles=excluded_titles,
            product_specs=product_specs,
            mode=mode,
            allow_empty=mode == QuantityInputMode.BASE_STOCK,
            apply_stock_range=True,
            allow_zero=False,
            max_packages=None,
        )
    except QuantityValidationError as error:
        raise FormQuantityValidationError(str(error)) from error
