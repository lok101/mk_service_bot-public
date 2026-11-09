from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class UnitCostRow:
    product_code: str
    unit_cost: Decimal
    valid_from: date
    valid_to: date | None


@beartype
def effective_unit_cost(
    rows: tuple[UnitCostRow, ...],
    *,
    product_code: str,
    as_of: date,
) -> Decimal | None:
    matching = [
        row
        for row in rows
        if row.product_code == product_code
        and row.valid_from <= as_of
        and (row.valid_to is None or as_of <= row.valid_to)
    ]
    if not matching:
        return None
    chosen = max(matching, key=lambda row: row.valid_from)
    return chosen.unit_cost
