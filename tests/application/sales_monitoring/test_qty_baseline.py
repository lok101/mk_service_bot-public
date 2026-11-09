from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.sales_monitoring.qty_baseline import like_day_qty_baseline_avg
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale

_TZ = ZoneInfo("Asia/Yekaterinburg")
_MACHINE = MachineId("m-a")
_REPORT_DAY = date(2026, 7, 27)  # Monday
_INGESTED = datetime(2026, 7, 28, 8, 5, tzinfo=_TZ)


def _sale(day: date, qty: Decimal, *, source_id: str) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE,
        product_code="sku-1",
        quantity=qty,
        occurred_at=datetime.combine(day, time(12, 0), tzinfo=_TZ),
        ingested_at=_INGESTED,
        price=Decimal("10"),
    )


def test_like_day_qty_baseline_matches_decline_fixture() -> None:
    """Four prior weekdays @ 100 → baseline 100 (min_points=4, no winsorize)."""
    sales_by_day: dict[date, tuple[MachineSale, ...]] = {}
    for i, offset in enumerate(range(1, 8)):
        day = _REPORT_DAY - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        sales_by_day[day] = (_sale(day, Decimal("100"), source_id=f"s-{i}"),)

    avg = like_day_qty_baseline_avg(
        report_day=_REPORT_DAY,
        by_day=sales_by_day,
        days_for_average=14,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    assert avg == Decimal("100")


def test_like_day_qty_baseline_insufficient_points_returns_none() -> None:
    day = _REPORT_DAY - timedelta(days=1)
    by_day = {day: (_sale(day, Decimal("50"), source_id="s-1"),)}
    assert (
        like_day_qty_baseline_avg(
            report_day=_REPORT_DAY,
            by_day=by_day,
            days_for_average=14,
            baseline_min_points=4,
            baseline_winsorize_min_points=8,
            baseline_winsorize_percent=10,
        )
        is None
    )
