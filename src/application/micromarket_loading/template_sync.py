from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class DesiredTemplateRow:
    product_id: int
    price_rub: Decimal
    category_id: int
    location_id: int
    disabled: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class TemplateRow:
    product_id: int
    price_rub: Decimal
    category_id: int
    location_id: int
    disabled: bool


@beartype
@dataclass(frozen=True, slots=True)
class TemplateSyncPlan:
    add_category_ids: tuple[int, ...]
    remove_product_ids: tuple[int, ...]
    add_rows: tuple[DesiredTemplateRow, ...]


def _same(desired: DesiredTemplateRow, current: TemplateRow) -> bool:
    return (
        desired.product_id == current.product_id
        and desired.price_rub == current.price_rub
        and desired.category_id == current.category_id
        and desired.location_id == current.location_id
        and desired.disabled == current.disabled
    )


@beartype
def plan_kit_shop_template_sync(
    *,
    desired: Sequence[DesiredTemplateRow],
    current: Sequence[TemplateRow],
    category_ids_on_template: Sequence[int],
) -> TemplateSyncPlan:
    desired_ids = {row.product_id for row in desired}
    current_by_id = {row.product_id: row for row in current}
    remove: list[int] = []
    add: list[DesiredTemplateRow] = []
    for current_row in current:
        if current_row.product_id not in desired_ids:
            remove.append(current_row.product_id)
    for desired_row in desired:
        existing = current_by_id.get(desired_row.product_id)
        if existing is None:
            add.append(desired_row)
        elif not _same(desired_row, existing):
            remove.append(desired_row.product_id)
            add.append(desired_row)
    present = set(category_ids_on_template)
    categories = tuple(
        category_id
        for category_id in dict.fromkeys(row.category_id for row in desired)
        if category_id not in present
    )
    return TemplateSyncPlan(
        add_category_ids=categories,
        remove_product_ids=tuple(remove),
        add_rows=tuple(add),
    )
