from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.application.machine_pnl.month_projection import (
    LookbackPeriod,
    coverage_days,
    known_window_end,
    ratio_from_lookback,
    split_period_amount,
    waterfall,
)


def test_revenue_weighted_split_uses_revenue_ratio() -> None:
    result = split_period_amount(
        amount=Decimal("100.00"),
        fragment_revenue=Decimal("40.00"),
        period_revenue=Decimal("80.00"),
        fragment_days=10,
        period_days=20,
    )
    assert result.value == Decimal("50.00")
    assert result.used_day_count_fallback is False


def test_revenue_weighted_split_zero_revenue_falls_back_to_days() -> None:
    result = split_period_amount(
        amount=Decimal("30.00"),
        fragment_revenue=Decimal("0"),
        period_revenue=Decimal("0"),
        fragment_days=10,
        period_days=20,
    )
    assert result.value == Decimal("15.00")
    assert result.used_day_count_fallback is True


def test_ratio_from_last_n_same_location_weighted_by_days() -> None:
    periods = (
        LookbackPeriod(location_id="loc-a", days=10, revenue=Decimal("100"), amount=Decimal("20")),
        LookbackPeriod(location_id="loc-a", days=20, revenue=Decimal("200"), amount=Decimal("80")),
    )
    result = ratio_from_lookback(periods, location_id="loc-a", last_n=3)
    assert result.basis == "last_n_periods_same_location"
    assert result.ratio == Decimal("10") / Decimal("30")


def test_ratio_ignores_other_location_periods() -> None:
    periods = (
        LookbackPeriod(
            location_id="loc-old", days=30, revenue=Decimal("100"), amount=Decimal("90")
        ),
        LookbackPeriod(location_id="loc-a", days=10, revenue=Decimal("50"), amount=Decimal("5")),
    )
    result = ratio_from_lookback(periods, location_id="loc-a", last_n=3)
    assert result.basis == "last_n_periods_same_location"
    assert result.ratio == Decimal("5") / Decimal("50")


def test_ratio_none_when_no_history() -> None:
    periods = (
        LookbackPeriod(
            location_id="loc-old", days=10, revenue=Decimal("100"), amount=Decimal("20")
        ),
    )
    result = ratio_from_lookback(periods, location_id="loc-new", last_n=3)
    assert result.basis == "none"
    assert result.ratio is None


def test_ratio_uses_available_when_fewer_than_n() -> None:
    periods = (
        LookbackPeriod(location_id="loc-a", days=10, revenue=Decimal("100"), amount=Decimal("10")),
    )
    result = ratio_from_lookback(periods, location_id="loc-a", last_n=3)
    assert result.basis == "last_n_periods_same_location"
    assert result.ratio == Decimal("10") / Decimal("100")


def test_known_window_clips_to_today() -> None:
    end = known_window_end(
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        today=date(2026, 6, 10),
    )
    assert end == date(2026, 6, 10)


def test_known_window_past_month_keeps_period_end() -> None:
    end = known_window_end(
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        today=date(2026, 6, 10),
    )
    assert end == date(2026, 5, 31)


def test_coverage_excludes_future_days() -> None:
    covered = ((date(2026, 6, 1), date(2026, 6, 8)),)
    result = coverage_days(
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        today=date(2026, 6, 10),
        closed_ranges=covered,
    )
    assert result.days_in_month == 30
    assert result.coverage_days == 8
    assert result.elapsed_days == 10
    assert result.coverage_pct == Decimal("8") / Decimal("30") * Decimal("100")


def test_waterfall_identities() -> None:
    wf = waterfall(
        revenue=Decimal("100.00"),
        cogs_expected=Decimal("40.00"),
        cogs_actual_total=Decimal("45.00"),
        opex_known_total=Decimal("10.00"),
        tech_gap=Decimal("3.00"),
    )
    assert wf.net_theory == Decimal("50.00")
    assert wf.machine_gap == Decimal("5.00")
    assert wf.net_machine == Decimal("45.00")
    assert wf.tech_gap == Decimal("3.00")
    assert wf.net_after_tech == Decimal("42.00")
    assert wf.net_theory - wf.machine_gap == wf.net_machine
    assert wf.net_machine - wf.tech_gap == wf.net_after_tech


def test_waterfall_excludes_surplus() -> None:
    wf = waterfall(
        revenue=Decimal("100.00"),
        cogs_expected=Decimal("40.00"),
        cogs_actual_total=Decimal("40.00"),
        opex_known_total=Decimal("10.00"),
        tech_gap=Decimal("0.00"),
    )
    assert wf.net_after_tech == wf.net_machine == Decimal("50.00")
