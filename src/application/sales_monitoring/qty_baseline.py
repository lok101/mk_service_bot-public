from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from math import floor
from typing import Literal

from beartype import beartype

from src.domain.machine_sales import MachineSale

LikeDayClass = Literal["weekday", "weekend"]


def _like_day_class(day: date) -> LikeDayClass:
    return "weekday" if day.weekday() < 5 else "weekend"


def _daily_qty(day_sales: Sequence[MachineSale]) -> Decimal | None:
    total = Decimal("0")
    for sale in day_sales:
        total += sale.quantity
    if total <= 0:
        return None
    return total


def _winsorized_mean(values: Sequence[Decimal], percent: int) -> Decimal:
    if not values:
        raise ValueError("empty values")
    if percent <= 0:
        return sum(values, Decimal("0")) / Decimal(len(values))
    ordered = sorted(values)
    n = len(ordered)
    lo_idx = floor((n - 1) * percent / 100)
    hi_idx = floor((n - 1) * (100 - percent) / 100)
    p_lo = ordered[lo_idx]
    p_hi = ordered[hi_idx]
    clipped = [min(max(v, p_lo), p_hi) for v in ordered]
    return sum(clipped, Decimal("0")) / Decimal(n)


@beartype
def like_day_qty_baseline_avg(
    *,
    report_day: date,
    by_day: Mapping[date, Sequence[MachineSale]],
    days_for_average: int,
    baseline_min_points: int,
    baseline_winsorize_min_points: int,
    baseline_winsorize_percent: int,
) -> Decimal | None:
    """Winsorized like-day mean of daily Σ quantity over lookback ending before report_day.

    Empty days are not points. None = insufficient points or non-positive mean.
    Semantics must match sales-monitoring decline baseline.
    """
    target = _like_day_class(report_day)
    points: list[Decimal] = []
    for offset in range(1, days_for_average + 1):
        day = report_day - timedelta(days=offset)
        if _like_day_class(day) != target:
            continue
        qty = _daily_qty(by_day.get(day, ()))
        if qty is not None:
            points.append(qty)

    if len(points) < baseline_min_points:
        return None

    if len(points) >= baseline_winsorize_min_points and baseline_winsorize_percent > 0:
        baseline_avg = _winsorized_mean(points, baseline_winsorize_percent)
    else:
        baseline_avg = sum(points, Decimal("0")) / Decimal(len(points))

    if baseline_avg <= 0:
        return None
    return baseline_avg
