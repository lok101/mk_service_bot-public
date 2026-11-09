from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.money import round_money

_ZERO = Decimal("0")
_RATIO_BASIS_LAST_N = "last_n_periods_same_location"
_RATIO_BASIS_NONE = "none"


@beartype
@dataclass(frozen=True, slots=True)
class PeriodSplit:
    value: Decimal
    used_day_count_fallback: bool


@beartype
def split_period_amount(
    *,
    amount: Decimal,
    fragment_revenue: Decimal,
    period_revenue: Decimal,
    fragment_days: int,
    period_days: int,
) -> PeriodSplit:
    if period_revenue == _ZERO:
        days = max(1, period_days)
        value = round_money(amount * Decimal(fragment_days) / Decimal(days))
        return PeriodSplit(value=value, used_day_count_fallback=True)
    value = round_money(amount * fragment_revenue / period_revenue)
    return PeriodSplit(value=value, used_day_count_fallback=False)


@beartype
@dataclass(frozen=True, slots=True)
class LookbackPeriod:
    location_id: str | None
    days: int
    revenue: Decimal
    amount: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class RatioResult:
    basis: str
    ratio: Decimal | None


@beartype
def ratio_from_lookback(
    periods: Sequence[LookbackPeriod],
    *,
    location_id: str | None,
    last_n: int,
) -> RatioResult:
    matched: list[LookbackPeriod] = []
    for period in periods:
        if period.location_id != location_id:
            continue
        if period.revenue == _ZERO:
            continue
        matched.append(period)
        if len(matched) >= last_n:
            break
    if not matched:
        return RatioResult(basis=_RATIO_BASIS_NONE, ratio=None)
    weighted = _ZERO
    total_days = 0
    for period in matched:
        weighted += (period.amount / period.revenue) * Decimal(period.days)
        total_days += period.days
    if total_days == 0:
        return RatioResult(basis=_RATIO_BASIS_NONE, ratio=None)
    return RatioResult(basis=_RATIO_BASIS_LAST_N, ratio=weighted / Decimal(total_days))


@beartype
def known_window_end(*, period_start: date, period_end: date, today: date) -> date:
    """Last calendar day of the month that is already known (not in the future)."""
    if today < period_start:
        return today
    return min(period_end, today)


@beartype
@dataclass(frozen=True, slots=True)
class CoverageResult:
    days_in_month: int
    coverage_days: int
    elapsed_days: int
    coverage_pct: Decimal


@beartype
def coverage_days(
    *,
    period_start: date,
    period_end: date,
    today: date,
    closed_ranges: Sequence[tuple[date, date]],
) -> CoverageResult:
    """Count calendar-day coverage of a month by closed periods.

    Day D is covered if some closed range has ``opened_date <= D <= closed_date``
    (inclusive dates) and D is in ``[period_start, known_end]``. Future days
    (``D > today``) are neither covered nor counted in elapsed days.
    ``coverage_pct`` is ``coverage_days / days_in_month * 100`` (not elapsed).
    """
    known_end = known_window_end(
        period_start=period_start,
        period_end=period_end,
        today=today,
    )
    days_in_month = (period_end - period_start).days + 1
    if known_end < period_start:
        elapsed_days = 0
        covered = 0
    else:
        elapsed_days = (known_end - period_start).days + 1
        covered = 0
        day = period_start
        while day <= known_end:
            if any(opened <= day <= closed for opened, closed in closed_ranges):
                covered += 1
            day += timedelta(days=1)
    coverage_pct = Decimal(covered) / Decimal(days_in_month) * Decimal("100")
    return CoverageResult(
        days_in_month=days_in_month,
        coverage_days=covered,
        elapsed_days=elapsed_days,
        coverage_pct=coverage_pct,
    )


@beartype
@dataclass(frozen=True, slots=True)
class Waterfall:
    net_theory: Decimal
    machine_gap: Decimal
    net_machine: Decimal
    tech_gap: Decimal
    net_after_tech: Decimal


@beartype
def waterfall(
    *,
    revenue: Decimal,
    cogs_expected: Decimal,
    cogs_actual_total: Decimal,
    opex_known_total: Decimal,
    tech_gap: Decimal,
) -> Waterfall:
    net_theory = round_money(revenue - cogs_expected - opex_known_total)
    machine_gap = round_money(cogs_actual_total - cogs_expected)
    net_machine = round_money(revenue - cogs_actual_total - opex_known_total)
    rounded_tech_gap = round_money(tech_gap)
    net_after_tech = round_money(net_machine - rounded_tech_gap)
    return Waterfall(
        net_theory=net_theory,
        machine_gap=machine_gap,
        net_machine=net_machine,
        tech_gap=rounded_tech_gap,
        net_after_tech=net_after_tech,
    )
