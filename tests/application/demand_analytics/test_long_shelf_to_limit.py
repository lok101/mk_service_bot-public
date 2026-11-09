from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.demand_analytics import (
    LONG_SHELF_TO_LIMIT_V1,
    SalesHistoryReadFailed,
)
from src.application.demand_analytics.long_shelf_to_limit import (
    LOOKBACK_CALENDAR_DAYS,
    LongShelfToLimitV1Policy,
)
from src.application.demand_analytics.ports import VirtualStockReadFailed

_ZONE = ZoneInfo("Asia/Yekaterinburg")
_HORIZON_START = datetime(2026, 10, 20, 12, 0, tzinfo=_ZONE)
_HORIZON_END = datetime(2026, 10, 22, 12, 0, tzinfo=_ZONE)  # 2 days


class _Sales:
    def __init__(
        self,
        rows: tuple[tuple[datetime, Decimal], ...] = (),
        *,
        fail: bool = False,
    ) -> None:
        self._rows = rows
        self._fail = fail
        self.last_sale_kind: str | None = None

    def list_quantities(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
        sale_kind: str | None = None,
    ) -> tuple[tuple[datetime, Decimal], ...] | SalesHistoryReadFailed:
        self.last_sale_kind = sale_kind
        if self._fail:
            return SalesHistoryReadFailed()
        return self._rows


class _Stock:
    def __init__(
        self,
        levels: tuple[tuple[datetime, Decimal], ...] = (),
        *,
        fail: bool = False,
    ) -> None:
        self._levels = levels
        self._fail = fail

    def list_levels(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[tuple[datetime, Decimal], ...] | VirtualStockReadFailed:
        if self._fail:
            return VirtualStockReadFailed()
        return self._levels


def _policy(
    stock: _Stock,
) -> LongShelfToLimitV1Policy:
    return LongShelfToLimitV1Policy(virtual_stock=stock)


def test_happy_path_target_10_shelf_4_expected_3_forecast_3() -> None:
    """target 10, shelf 4, expected 3 → projected 1 → desired 9 → gap 6 → forecast 3."""
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    # Q>0 for exactly 1 day; S=1.5 → rate=1.5/day; horizon 2d → expected=3
    stock = _Stock(
        (
            (lookback_open, Decimal("10")),
            (lookback_open + timedelta(days=1), Decimal("0")),
        )
    )
    sales = _Sales(((lookback_open + timedelta(hours=1), Decimal("1.5")),))
    result = _policy(stock).forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("4"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    assert sales.last_sale_kind == "micromarket"
    assert result == Decimal("3")


def test_zero_sales_with_positive_stock_returns_zero_forecast() -> None:
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    stock = _Stock(((lookback_open + timedelta(hours=1), Decimal("4")),))
    sales = _Sales(())
    result = _policy(stock).forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("4"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    # expected 0 → projected=shelf → desired=gap → forecast 0
    assert result == Decimal("0")


def test_no_positive_stock_time_unavailable() -> None:
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    stock = _Stock(((lookback_open + timedelta(hours=1), Decimal("0")),))
    sales = _Sales(((lookback_open + timedelta(hours=2), Decimal("1")),))
    result = _policy(stock).forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("0"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    assert result is None


def test_clip_after_round_half_up_keeps_need_at_most_desired() -> None:
    """Raw addend rounds up; clip so gap + forecast ≤ desired."""
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    # rate = 1 / day; horizon 0.6d → expected 0.6
    # shelf 4, target 10 → projected = max(0, 4-0.6)=3.4 → desired=6.6
    # gap=6 → raw=0.6 → ROUND_HALF_UP=1 → without clip need=7 > desired 6.6
    # with clip forecast ≤ floor(desired - gap) in integer terms: gap+forecast ≤ desired
    stock = _Stock(
        (
            (lookback_open, Decimal("1")),
            (lookback_open + timedelta(days=1), Decimal("0")),
        )
    )
    sales = _Sales(((lookback_open + timedelta(hours=1), Decimal("1")),))
    horizon_end = _HORIZON_START + timedelta(hours=14, minutes=24)  # 0.6 days
    result = _policy(stock).forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=horizon_end,
        shelf_qty=Decimal("4"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    gap = Decimal("6")
    desired = Decimal("10") - max(Decimal("0"), Decimal("4") - Decimal("0.6"))
    assert result is not None
    assert not isinstance(result, (SalesHistoryReadFailed, VirtualStockReadFailed))
    assert gap + result <= desired


def test_sales_read_failed_propagates() -> None:
    stock = _Stock(((_HORIZON_START - timedelta(days=1), Decimal("2")),))
    sales = _Sales(fail=True)
    result = _policy(stock).forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("2"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    assert isinstance(result, SalesHistoryReadFailed)


def test_stock_read_failed_propagates() -> None:
    stock = _Stock(fail=True)
    sales = _Sales(())
    result = _policy(stock).forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("2"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    assert isinstance(result, VirtualStockReadFailed)


def test_policy_key_constant() -> None:
    assert LONG_SHELF_TO_LIMIT_V1 == "long_shelf_to_limit_v1"
    assert LongShelfToLimitV1Policy.policy_key == LONG_SHELF_TO_LIMIT_V1
