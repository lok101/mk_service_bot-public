from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.demand_analytics.ports import (
    SalesHistoryReadFailed,
    SkuSalesHistoryPort,
    SkuVirtualStockHistoryPort,
    VirtualStockReadFailed,
)

LOOKBACK_CALENDAR_DAYS = 14
_SECONDS_PER_DAY = Decimal("86400")
_SALE_KIND = "micromarket"
_POLICY_KEY = "short_shelf_lead_time_v1"


@beartype
def _duration_days(start: datetime, end: datetime) -> Decimal:
    seconds = Decimal(str((end - start).total_seconds()))
    if seconds <= 0:
        return Decimal("0")
    return seconds / _SECONDS_PER_DAY


@beartype
def positive_stock_days(
    levels: tuple[tuple[datetime, Decimal], ...],
    *,
    opened_at: datetime,
    closed_at: datetime,
) -> Decimal:
    """Integrate days inside ``[opened_at, closed_at)`` where virtual Q > 0."""
    if closed_at <= opened_at:
        return Decimal("0")
    ordered = tuple(sorted(levels, key=lambda row: row[0]))
    qty = Decimal("0")
    for at, level in ordered:
        if at <= opened_at:
            qty = level
        else:
            break
    cursor = opened_at
    total = Decimal("0")
    for at, level in ordered:
        if at <= opened_at:
            continue
        if at >= closed_at:
            break
        if qty > 0:
            total += _duration_days(cursor, at)
        cursor = at
        qty = level
    if qty > 0:
        total += _duration_days(cursor, closed_at)
    return total


@beartype
class ShortShelfLeadTimeV1Policy:
    """Sell-through rate while virtual stock is positive; cap by ``shelf_qty``."""

    policy_key = _POLICY_KEY

    def __init__(self, *, virtual_stock: SkuVirtualStockHistoryPort) -> None:
        self._virtual_stock = virtual_stock

    @beartype
    def forecast(
        self,
        *,
        machine_id: str,
        product_code: str,
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
        timezone: ZoneInfo,
        history: SkuSalesHistoryPort,
    ) -> Decimal | None | SalesHistoryReadFailed | VirtualStockReadFailed:
        del target_qty  # unused by this policy
        local_start = horizon_start.astimezone(timezone)
        lookback_open = local_start - timedelta(days=LOOKBACK_CALENDAR_DAYS)
        lookback_close = horizon_start

        sales = history.list_quantities(
            machine_id=machine_id,
            product_code=product_code,
            opened_at=lookback_open,
            closed_at=lookback_close,
            sale_kind=_SALE_KIND,
        )
        if isinstance(sales, SalesHistoryReadFailed):
            return sales

        levels = self._virtual_stock.list_levels(
            machine_id=machine_id,
            product_code=product_code,
            opened_at=lookback_open,
            closed_at=lookback_close,
        )
        if isinstance(levels, VirtualStockReadFailed):
            return levels

        t_plus = positive_stock_days(
            levels,
            opened_at=lookback_open,
            closed_at=lookback_close,
        )
        if t_plus == 0:
            return None

        sold = sum((qty for _at, qty in sales), Decimal("0"))
        rate = sold / t_plus
        horizon_days = _duration_days(horizon_start, horizon_end)
        raw = rate * horizon_days
        capped = min(raw, max(Decimal("0"), shelf_qty))
        return capped.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
