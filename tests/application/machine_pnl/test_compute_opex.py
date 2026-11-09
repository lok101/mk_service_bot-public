from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.opex import OpExComputation, compute_opex, period_days
from src.application.machine_pnl.opex_params import (
    DutyMode,
    EffectiveOpExParams,
)

_ZERO = Decimal("0.00")


def test_period_days_same_calendar_day_is_one() -> None:
    opened = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 10, 18, 0, tzinfo=UTC)
    assert period_days(opened_at=opened, closed_at=closed) == 1


def test_period_days_multi_day() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    assert period_days(opened_at=opened, closed_at=closed) == 10


def _full_params(
    *,
    rent_monthly: Decimal | None = Decimal("310"),
    rent_percent: Decimal | None = Decimal("10"),
    duty_mode: DutyMode = "patent",
    patent_monthly: Decimal | None = Decimal("0"),
    tax_percent: Decimal | None = None,
    acquiring_percent: Decimal | None = Decimal("0"),
    acquiring_fee_per_sale: Decimal | None = Decimal("0"),
    terminal_monthly: Decimal | None = Decimal("0"),
    labor_rate: Decimal | None = Decimal("50"),
    params_incomplete: bool = False,
    missing_labor_rate: bool = False,
) -> EffectiveOpExParams:
    return EffectiveOpExParams(
        rent_monthly=rent_monthly,
        rent_percent=rent_percent,
        duty_mode=duty_mode,
        patent_monthly=patent_monthly,
        tax_percent=tax_percent,
        acquiring_percent=acquiring_percent,
        acquiring_fee_per_sale=acquiring_fee_per_sale,
        terminal_monthly=terminal_monthly,
        labor_rate=labor_rate,
        params_incomplete=params_incomplete,
        missing_labor_rate=missing_labor_rate,
    )


def _breakdown_map(result: OpExComputation) -> dict[str, Decimal | None]:
    return dict(result.breakdown)


def test_compute_opex_params_rent_ignored_uses_kwargs() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            rent_monthly=Decimal("999"),
            rent_percent=Decimal("50"),
            params_incomplete=True,
        ),
        revenue=Decimal("100"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    by_key = _breakdown_map(result)
    assert by_key["rent_fixed"] == Decimal("0.00")
    assert by_key["rent_percent"] == Decimal("0.00")
    assert any(w.code == "opex_params_incomplete" for w in result.warnings)


def test_compute_opex_rent_hybrid_prorata_and_percent() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    rent_fixed = round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    rent_percent = round_money(Decimal("10"))
    result = compute_opex(
        params=_full_params(),
        revenue=Decimal("100"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=rent_fixed,
        rent_percent=rent_percent,
        tax_enabled=True,
    )
    by_key = _breakdown_map(result)
    assert by_key["rent_fixed"] == rent_fixed
    assert by_key["rent_percent"] == rent_percent
    assert result.warnings == ()


def test_compute_opex_patent_pending_when_monthly_missing() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            duty_mode="patent",
            patent_monthly=None,
            tax_percent=None,
            rent_monthly=Decimal("0"),
            rent_percent=None,
            params_incomplete=False,
        ),
        revenue=Decimal("500"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=False,
    )
    patent_map = _breakdown_map(result)
    assert patent_map["patent"] == Decimal("0.00")
    assert any(w.code == "patent_pending_manual" for w in result.warnings)


def test_compute_opex_patent_xor_tax() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    patent_result = compute_opex(
        params=_full_params(
            duty_mode="patent",
            patent_monthly=Decimal("310"),
            tax_percent=Decimal("15"),
            rent_monthly=Decimal("0"),
            rent_percent=None,
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=True,
    )
    patent_map = _breakdown_map(patent_result)
    assert patent_map["patent"] == round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    assert patent_map["tax"] == Decimal("0.00")

    tax_result = compute_opex(
        params=_full_params(
            duty_mode="tax",
            patent_monthly=Decimal("310"),
            tax_percent=Decimal("15"),
            rent_monthly=Decimal("0"),
            rent_percent=None,
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=True,
    )
    tax_map = _breakdown_map(tax_result)
    assert tax_map["tax"] == round_money(Decimal("15") / Decimal("100") * Decimal("200"))
    assert tax_map["patent"] == Decimal("0.00")


def test_compute_opex_tax_known_excluded_from_opex() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            duty_mode="tax",
            patent_monthly=None,
            tax_percent=Decimal("15"),
            rent_monthly=Decimal("0"),
            rent_percent=None,
            acquiring_percent=Decimal("0"),
            acquiring_fee_per_sale=Decimal("0"),
            terminal_monthly=Decimal("0"),
            labor_rate=None,
            missing_labor_rate=True,
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=True,
    )
    by_key = _breakdown_map(result)
    expected_tax = round_money(Decimal("15") / Decimal("100") * Decimal("200"))
    assert by_key["tax"] == expected_tax
    assert result.opex == Decimal("0.00")
    assert not any(w.code == "tax_pending_manual" for w in result.warnings)


def test_compute_opex_tax_pending_manual_null() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    expected_rent = round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    result = compute_opex(
        params=_full_params(
            duty_mode="tax",
            patent_monthly=None,
            tax_percent=None,
            rent_monthly=Decimal("310"),
            rent_percent=None,
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=expected_rent,
        rent_percent=_ZERO,
    )
    by_key = _breakdown_map(result)
    assert by_key["tax"] is None
    assert any(w.code == "tax_pending_manual" for w in result.warnings)


def test_compute_opex_tax_disabled_forces_pending_even_with_percent() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            duty_mode="tax",
            patent_monthly=None,
            tax_percent=Decimal("15"),
            rent_monthly=Decimal("0"),
            rent_percent=None,
            acquiring_percent=Decimal("0"),
            acquiring_fee_per_sale=Decimal("0"),
            terminal_monthly=Decimal("0"),
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=False,
    )
    by_key = _breakdown_map(result)
    assert by_key["tax"] is None
    assert result.opex == Decimal("0.00")
    assert any(w.code == "tax_pending_manual" for w in result.warnings)


def test_compute_opex_default_tax_enabled_is_false() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(duty_mode="tax", tax_percent=Decimal("6")),
        revenue=Decimal("100"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        # tax_enabled intentionally omitted
    )
    by_key = _breakdown_map(result)
    assert by_key["tax"] is None
    assert any(w.code == "tax_pending_manual" for w in result.warnings)


def test_compute_opex_tax_disabled_forces_pending_on_patent() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            duty_mode="patent",
            patent_monthly=Decimal("310"),
            tax_percent=None,
            rent_monthly=Decimal("0"),
            rent_percent=None,
            acquiring_percent=Decimal("0"),
            acquiring_fee_per_sale=Decimal("0"),
            terminal_monthly=Decimal("0"),
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=False,
    )
    by_key = _breakdown_map(result)
    assert by_key["tax"] is None
    assert by_key["patent"] == round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    assert any(w.code == "tax_pending_manual" for w in result.warnings)


def test_compute_opex_patent_tax_zero_no_pending() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            duty_mode="patent",
            patent_monthly=Decimal("310"),
            tax_percent=Decimal("15"),
            rent_monthly=Decimal("0"),
            rent_percent=None,
        ),
        revenue=Decimal("200"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
        tax_enabled=True,
    )
    by_key = _breakdown_map(result)
    assert by_key["tax"] == Decimal("0.00")
    assert not any(w.code == "tax_pending_manual" for w in result.warnings)
    expected_patent = round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    assert result.opex == expected_patent


def test_compute_opex_acquiring_hybrid_excludes_null_price() -> None:
    # Caller: sale_count = sum(1 for s in sales if s.price is not None); fragment 03.
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            rent_monthly=Decimal("0"),
            rent_percent=None,
            patent_monthly=Decimal("0"),
            acquiring_percent=Decimal("1"),
            acquiring_fee_per_sale=Decimal("0.5"),
        ),
        revenue=Decimal("200"),
        sale_count=2,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    by_key = _breakdown_map(result)
    expected_pct = round_money(Decimal("1") / Decimal("100") * Decimal("200"))
    assert by_key["acquiring_percent"] == expected_pct
    assert by_key["acquiring_per_sale"] == round_money(Decimal("0.5") * Decimal("2"))


def test_compute_opex_labor_global_times_count() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            rent_monthly=Decimal("0"),
            rent_percent=None,
            patent_monthly=Decimal("0"),
            labor_rate=Decimal("50"),
        ),
        revenue=Decimal("0"),
        sale_count=0,
        maintenance_count=3,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    by_key = _breakdown_map(result)
    assert by_key["labor"] == Decimal("150.00")
    assert by_key["route_fuel"] == Decimal("0.00")


def test_compute_opex_terminal_prorata() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=_full_params(
            rent_monthly=Decimal("0"),
            rent_percent=None,
            patent_monthly=Decimal("0"),
            terminal_monthly=Decimal("310"),
        ),
        revenue=Decimal("0"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    by_key = _breakdown_map(result)
    assert by_key["terminal"] == round_money(Decimal("310") * Decimal("10") / Decimal("31"))


def test_compute_opex_breakdown_sum_equals_opex_excluding_tax() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    rent_fixed = round_money(Decimal("310") * Decimal("10") / Decimal("31"))
    rent_percent = round_money(Decimal("10"))
    result = compute_opex(
        params=_full_params(
            rent_monthly=Decimal("310"),
            rent_percent=Decimal("10"),
            duty_mode="tax",
            patent_monthly=None,
            tax_percent=Decimal("15"),
            acquiring_percent=Decimal("1"),
            acquiring_fee_per_sale=Decimal("0.5"),
            terminal_monthly=Decimal("310"),
            labor_rate=Decimal("50"),
            missing_labor_rate=False,
        ),
        revenue=Decimal("100"),
        sale_count=2,
        maintenance_count=3,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=rent_fixed,
        rent_percent=rent_percent,
        tax_enabled=True,
    )
    total = sum(
        (amount for key, amount in result.breakdown if key != "tax" and amount is not None),
        Decimal("0"),
    )
    assert round_money(total) == result.opex
    assert _breakdown_map(result)["tax"] == round_money(
        Decimal("15") / Decimal("100") * Decimal("100")
    )
    assert _breakdown_map(result)["route_fuel"] == Decimal("0.00")


def test_compute_opex_incomplete_and_missing_labor_warnings() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)

    incomplete = compute_opex(
        params=_full_params(
            rent_monthly=None,
            rent_percent=None,
            patent_monthly=None,
            acquiring_percent=None,
            acquiring_fee_per_sale=None,
            terminal_monthly=None,
            labor_rate=None,
            missing_labor_rate=True,
            params_incomplete=True,
        ),
        revenue=Decimal("100"),
        sale_count=0,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    incomplete_map = _breakdown_map(incomplete)
    assert incomplete_map["rent_fixed"] == Decimal("0.00")
    assert incomplete_map["rent_percent"] == Decimal("0.00")
    assert incomplete_map["patent"] == Decimal("0.00")
    assert incomplete.opex == Decimal("0.00")
    assert any(w.code == "opex_params_incomplete" for w in incomplete.warnings)

    missing_labor = compute_opex(
        params=_full_params(
            rent_monthly=Decimal("0"),
            rent_percent=None,
            patent_monthly=Decimal("0"),
            labor_rate=None,
            missing_labor_rate=True,
        ),
        revenue=Decimal("0"),
        sale_count=0,
        maintenance_count=2,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    assert _breakdown_map(missing_labor)["labor"] == Decimal("0.00")
    assert any(w.code == "missing_labor_rate" for w in missing_labor.warnings)


def test_compute_opex_incomplete_still_applies_acquiring_and_terminal() -> None:
    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)  # 10 days; May has 31
    result = compute_opex(
        params=_full_params(
            rent_monthly=None,
            rent_percent=None,
            patent_monthly=None,
            acquiring_percent=Decimal("2"),
            acquiring_fee_per_sale=Decimal("1.50"),
            terminal_monthly=Decimal("310"),
            labor_rate=None,
            missing_labor_rate=True,
            params_incomplete=True,
        ),
        revenue=Decimal("1000"),
        sale_count=4,
        maintenance_count=0,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    by_key = _breakdown_map(result)
    assert by_key["acquiring_percent"] == Decimal("20.00")
    assert by_key["acquiring_per_sale"] == Decimal("6.00")
    assert by_key["terminal"] == Decimal("100.00")  # 310 * 10 / 31
    assert by_key["patent"] == Decimal("0.00")
    assert any(w.code == "opex_params_incomplete" for w in result.warnings)
    assert result.opex == Decimal("126.00")
