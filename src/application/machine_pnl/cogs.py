from __future__ import annotations

from decimal import Decimal

from beartype import beartype


@beartype
def physical_qty(
    *,
    actual_prev: Decimal,
    loads_total: Decimal,
    actual: Decimal,
) -> Decimal:
    return actual_prev + loads_total - actual


@beartype
def cogs_expected_for_line(*, sales_total: Decimal, unit_cost: Decimal) -> Decimal:
    return sales_total * unit_cost


@beartype
def cogs_actual_for_line(*, physical: Decimal, unit_cost: Decimal) -> Decimal:
    return physical * unit_cost
