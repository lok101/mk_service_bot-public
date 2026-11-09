from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.inventory_reconciliation.errors import (
    DuplicateProductCodeInStock,
    NaiveDatetimeNotAllowed,
)
from src.domain.inventory_reconciliation.models import (
    PeriodLoadLine,
    PeriodReconciliationResult,
    PeriodRevisionStock,
    PeriodSaleLine,
    ReconciliationLine,
)

StockSource = Literal["actual_prev", "actual"]


def _is_naive(dt: datetime) -> bool:
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


def _require_aware(dt: datetime, *, field: str) -> NaiveDatetimeNotAllowed | None:
    if _is_naive(dt):
        return NaiveDatetimeNotAllowed(field=field)
    return None


def _stock_map(
    stock: PeriodRevisionStock,
    *,
    source: StockSource,
) -> dict[str, Decimal] | DuplicateProductCodeInStock:
    mapped: dict[str, Decimal] = {}
    for product_code, quantity in stock.lines:
        if product_code in mapped:
            return DuplicateProductCodeInStock(product_code=product_code, source=source)
        mapped[product_code] = quantity
    return mapped


def _in_window(occurred_at: datetime, *, opened_at: datetime, closed_at: datetime) -> bool:
    return opened_at < occurred_at <= closed_at


@beartype
def calculate_period_reconciliation(
    *,
    actual_prev: PeriodRevisionStock,
    actual: PeriodRevisionStock,
    loads: tuple[PeriodLoadLine, ...],
    sales: tuple[PeriodSaleLine, ...],
    opened_at: datetime,
    closed_at: datetime,
) -> PeriodReconciliationResult | DuplicateProductCodeInStock | NaiveDatetimeNotAllowed:
    for field_name, dt in (
        ("opened_at", opened_at),
        ("closed_at", closed_at),
    ):
        if err := _require_aware(dt, field=field_name):
            return err

    for index, load in enumerate(loads):
        if err := _require_aware(load.occurred_at, field=f"loads[{index}].occurred_at"):
            return err

    for index, sale in enumerate(sales):
        if err := _require_aware(sale.occurred_at, field=f"sales[{index}].occurred_at"):
            return err

    prev_mapped = _stock_map(actual_prev, source="actual_prev")
    if isinstance(prev_mapped, DuplicateProductCodeInStock):
        return prev_mapped

    actual_mapped = _stock_map(actual, source="actual")
    if isinstance(actual_mapped, DuplicateProductCodeInStock):
        return actual_mapped

    prev_map = prev_mapped
    actual_map = actual_mapped
    load_totals: dict[str, Decimal] = defaultdict(Decimal)
    sale_totals: dict[str, Decimal] = defaultdict(Decimal)

    for load in loads:
        if _in_window(load.occurred_at, opened_at=opened_at, closed_at=closed_at):
            load_totals[load.product_code] += load.base_quantity

    for sale in sales:
        if _in_window(sale.occurred_at, opened_at=opened_at, closed_at=closed_at):
            sale_totals[sale.product_code] += sale.quantity

    product_codes = set(prev_map) | set(actual_map) | set(load_totals) | set(sale_totals)
    lines: dict[str, ReconciliationLine] = {}
    for product_code in sorted(product_codes):
        actual_prev_qty = prev_map.get(product_code, Decimal("0"))
        actual_qty = actual_map.get(product_code, Decimal("0"))
        calculated = actual_prev_qty + load_totals[product_code] - sale_totals[product_code]
        lines[product_code] = ReconciliationLine(
            product_code=product_code,
            actual_prev=actual_prev_qty,
            actual=actual_qty,
            calculated=calculated,
            delta=actual_qty - calculated,
            loads_total=load_totals[product_code],
            sales_total=sale_totals[product_code],
        )
    return PeriodReconciliationResult(lines_by_product=lines)
