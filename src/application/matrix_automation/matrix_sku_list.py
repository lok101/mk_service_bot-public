from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.matrix_sku_catalog import (
    DEFAULT_PRODUCT_MULTIPLIER,
    MatrixSkuCatalogEntry,
)


@beartype
@dataclass(frozen=True, slots=True)
class MatrixSkuListRow:
    product_code: str
    display_name: str
    capacity: int | None
    product_multiplier: Decimal
    needs_capacity_highlight: bool
    is_archived: bool


@beartype
def build_matrix_sku_catalog_rows(
    ms_by_code: Mapping[str, tuple[str, bool]],
    entries: Sequence[MatrixSkuCatalogEntry],
) -> tuple[MatrixSkuListRow, ...]:
    by_entry = {e.product_code: e for e in entries}
    rows: list[MatrixSkuListRow] = []
    for code, (ms_name, archived) in ms_by_code.items():
        entry = by_entry.get(code)
        if entry is None:
            capacity: int | None = None
            name = ms_name
            multiplier = DEFAULT_PRODUCT_MULTIPLIER
        else:
            capacity = entry.capacity
            name = entry.display_name
            multiplier = entry.product_multiplier
        highlight = capacity is None or capacity <= 0
        rows.append(
            MatrixSkuListRow(
                product_code=code,
                display_name=name,
                capacity=capacity,
                product_multiplier=multiplier,
                needs_capacity_highlight=highlight,
                is_archived=archived,
            )
        )
    rows.sort(
        key=lambda r: (
            1 if r.is_archived else 0,
            0 if r.needs_capacity_highlight else 1,
            r.product_code,
        )
    )
    return tuple(rows)
