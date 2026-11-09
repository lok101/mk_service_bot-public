from __future__ import annotations

from beartype import beartype

from src.application.form_submissions.quantity_validation import ValidatedInventoryLine
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
    FrozenProductSpec,
)
from src.domain.product_catalog import ProductSpec


@beartype
def product_spec_to_frozen(spec: ProductSpec) -> FrozenProductSpec:
    return FrozenProductSpec(
        product_code=spec.product_code,
        name=spec.name,
        unit=spec.unit,
        pack_size=spec.pack_size,
        moysklad_quantity_factor=spec.moysklad_quantity_factor,
    )


@beartype
def validated_line_to_frozen(
    line: ValidatedInventoryLine,
    *,
    form_title: str,
) -> FrozenInventoryLine:
    return FrozenInventoryLine(
        form_title=form_title,
        product_spec=product_spec_to_frozen(line.product_spec),
        quantity=line.quantity,
    )


@beartype
def frozen_line_to_validated(line: FrozenInventoryLine) -> ValidatedInventoryLine:
    spec = line.product_spec
    return ValidatedInventoryLine(
        product_spec=ProductSpec(
            product_code=spec.product_code,
            name=spec.name,
            unit=spec.unit,
            pack_size=spec.pack_size,
            min_stock=None,
            max_stock=None,
            allow_fraction=True,
            moysklad_quantity_factor=spec.moysklad_quantity_factor,
        ),
        quantity=line.quantity,
    )


@beartype
def validated_lines_to_frozen(
    answers: tuple[FormAnswer, ...],
    lines: list[ValidatedInventoryLine],
    *,
    excluded_titles: frozenset[str],
) -> tuple[FrozenInventoryLine, ...]:
    frozen: list[FrozenInventoryLine] = []
    line_index = 0
    for answer in answers:
        title = answer.title.strip()
        if not title or title in excluded_titles:
            continue
        if line_index >= len(lines):
            raise ValueError("validated line count does not match product answers")
        frozen.append(
            validated_line_to_frozen(lines[line_index], form_title=title),
        )
        line_index += 1
    if line_index != len(lines):
        raise ValueError("validated line count does not match product answers")
    return tuple(frozen)


@beartype
def validated_lines_from_snapshot(snapshot: FormSubmissionSnapshot) -> list[ValidatedInventoryLine]:
    return [frozen_line_to_validated(line) for line in snapshot.validated_lines]
