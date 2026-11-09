from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.demand_analytics import (
    SHORT_SHELF_LEAD_TIME_V1,
    SalesHistoryReadFailed,
)
from src.application.demand_analytics.ports import VirtualStockReadFailed
from src.application.demand_analytics.short_shelf_lead_time import (
    LOOKBACK_CALENDAR_DAYS,
    ShortShelfLeadTimeV1Policy,
)

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


def test_sell_out_then_empty_shelf_yields_high_rate_capped_by_shelf() -> None:
    """Batch of 5 sold in one day; rest of lookback Q=0 — high rate, not unavailable."""
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    day0 = lookback_open + timedelta(days=1)
    # Q goes 5 → 0 at end of day0; stays 0
    stock = _Stock(
        (
            (day0, Decimal("5")),
            (day0 + timedelta(hours=20), Decimal("0")),
        )
    )
    sales = _Sales(((day0 + timedelta(hours=10), Decimal("5")),))
    policy = ShortShelfLeadTimeV1Policy(virtual_stock=stock)
    result = policy.forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("3"),
        target_qty=Decimal("99"),
        timezone=_ZONE,
        history=sales,
    )
    assert sales.last_sale_kind == "micromarket"
    # rate ≈ 5 / (20/24) = 6; × 2 days ≈ 12; cap shelf 3 → 3
    assert result == Decimal("3")


def test_zero_sales_with_positive_stock_time_returns_zero() -> None:
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    stock = _Stock(((lookback_open + timedelta(hours=1), Decimal("4")),))
    sales = _Sales(())
    policy = ShortShelfLeadTimeV1Policy(virtual_stock=stock)
    result = policy.forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        shelf_qty=Decimal("4"),
        target_qty=Decimal("10"),
        timezone=_ZONE,
        history=sales,
    )
    assert result == Decimal("0")


def test_no_positive_stock_time_unavailable() -> None:
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    stock = _Stock(((lookback_open + timedelta(hours=1), Decimal("0")),))
    sales = _Sales(((lookback_open + timedelta(hours=2), Decimal("1")),))
    policy = ShortShelfLeadTimeV1Policy(virtual_stock=stock)
    result = policy.forecast(
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


def test_sales_read_failed_propagates() -> None:
    stock = _Stock(((_HORIZON_START - timedelta(days=1), Decimal("2")),))
    sales = _Sales(fail=True)
    policy = ShortShelfLeadTimeV1Policy(virtual_stock=stock)
    result = policy.forecast(
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
    policy = ShortShelfLeadTimeV1Policy(virtual_stock=stock)
    result = policy.forecast(
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
    assert SHORT_SHELF_LEAD_TIME_V1 == "short_shelf_lead_time_v1"
    assert ShortShelfLeadTimeV1Policy.policy_key == SHORT_SHELF_LEAD_TIME_V1


def test_round_half_up_and_ignore_target() -> None:
    """Partial horizon fraction with rate that needs HALF_UP."""
    lookback_open = _HORIZON_START - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    # Q>0 for exactly 1 day; S=1 → rate=1/day
    stock = _Stock(
        (
            (lookback_open, Decimal("1")),
            (lookback_open + timedelta(days=1), Decimal("0")),
        )
    )
    sales = _Sales(((lookback_open + timedelta(hours=1), Decimal("1")),))
    # horizon 1.5 days → raw 1.5 → round half up → 2; shelf allows 10
    horizon_end = _HORIZON_START + timedelta(hours=36)
    policy = ShortShelfLeadTimeV1Policy(virtual_stock=stock)
    result = policy.forecast(
        machine_id="m1",
        product_code="SKU-1",
        horizon_start=_HORIZON_START,
        horizon_end=horizon_end,
        shelf_qty=Decimal("10"),
        target_qty=Decimal("1"),
        timezone=_ZONE,
        history=sales,
    )
    assert result == Decimal("2")
