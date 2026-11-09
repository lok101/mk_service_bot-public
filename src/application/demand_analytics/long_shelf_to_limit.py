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
from src.application.demand_analytics.short_shelf_lead_time import (
    LOOKBACK_CALENDAR_DAYS,
    positive_stock_days,
)

_SECONDS_PER_DAY = Decimal("86400")
_SALE_KIND = "micromarket"
_POLICY_KEY = "long_shelf_to_limit_v1"


@beartype
def _duration_days(start: datetime, end: datetime) -> Decimal:
    seconds = Decimal(str((end - start).total_seconds()))
    if seconds <= 0:
        return Decimal("0")
    return seconds / _SECONDS_PER_DAY


@beartype
class LongShelfToLimitV1Policy:
    """Rate while Q>0; forecast is addend so need reaches desired without overfill."""

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
        expected = rate * horizon_days
        projected = max(Decimal("0"), shelf_qty - expected)
        desired = max(Decimal("0"), target_qty - projected)
        gap_equiv = max(Decimal("0"), target_qty - shelf_qty)
        raw = max(Decimal("0"), desired - gap_equiv)
        forecast = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        # Clip so integer need does not exceed desired after round-up.
        max_addend = max(Decimal("0"), desired - gap_equiv)
        if forecast > max_addend:
            forecast = max_addend.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            while gap_equiv + forecast > desired and forecast > 0:
                forecast -= Decimal("1")
        return forecast
