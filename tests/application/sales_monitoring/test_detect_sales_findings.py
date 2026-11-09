from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.sales_monitoring.detect_sales_findings import detect_sales_findings
from src.application.sales_monitoring.exclude import union_excluded_machine_codes
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.domain.sales_monitoring.event_ids import sales_finding_event_id
from src.domain.sales_monitoring.events import (
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)

_TZ = ZoneInfo("Asia/Yekaterinburg")
_MACHINE_A = MachineId("m-a")
_MACHINE_B = MachineId("m-b")
_REPORT_DAY = date(2026, 7, 27)
_OCCURRED_AT = datetime(2026, 7, 28, 8, 0, tzinfo=_TZ)
_INGESTED_AT = datetime(2026, 7, 28, 8, 5, tzinfo=_TZ)


def _sale(
    *,
    source_id: str,
    machine_id: MachineId,
    day: date,
    hour: int = 12,
    price: Decimal | None,
    quantity: Decimal = Decimal("1"),
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=machine_id,
        product_code="sku-1",
        quantity=quantity,
        occurred_at=datetime.combine(day, time(hour, 0), tzinfo=_TZ),
        ingested_at=_INGESTED_AT,
        price=price,
    )


def _detect(
    *,
    sales: tuple[MachineSale, ...],
    catalog_machine_ids: tuple[MachineId, ...] = (_MACHINE_A,),
    excluded_codes: frozenset[str] = frozenset(),
    report_day: date = _REPORT_DAY,
    days_for_average: int = 14,
    sales_drop_percent: int = 30,
    baseline_min_points: int = 4,
    baseline_winsorize_min_points: int = 8,
    baseline_winsorize_percent: int = 10,
    branch: str = "yesterday",
    occurred_at: datetime = _OCCURRED_AT,
    no_sales_habitual_max_nonempty: int = 1,
):
    return detect_sales_findings(
        catalog_machine_ids=catalog_machine_ids,
        excluded_codes=excluded_codes,
        sales=sales,
        report_day=report_day,
        timezone=_TZ,
        days_for_average=days_for_average,
        sales_drop_percent=sales_drop_percent,
        baseline_min_points=baseline_min_points,
        baseline_winsorize_min_points=baseline_winsorize_min_points,
        baseline_winsorize_percent=baseline_winsorize_percent,
        branch=branch,  # type: ignore[arg-type]
        occurred_at=occurred_at,
        no_sales_habitual_max_nonempty=no_sales_habitual_max_nonempty,
    )


def test_weekend_no_sales_skipped_when_habitual_quiet() -> None:
    report_day = date(2026, 8, 8)  # Saturday
    prior_weekend = date(2026, 8, 2)  # Sunday
    sales = (
        _sale(
            source_id="w1",
            machine_id=_MACHINE_A,
            day=prior_weekend,
            price=Decimal("100"),
        ),
    )
    findings = _detect(
        sales=sales,
        report_day=report_day,
        days_for_average=28,
        no_sales_habitual_max_nonempty=1,
        branch="yesterday",
    )
    assert not any(isinstance(f, SalesMonitoringYesterdayNoSales) for f in findings)


def test_weekend_today_no_sales_skipped_when_habitual_quiet() -> None:
    report_day = date(2026, 8, 8)  # Saturday
    sales = (
        _sale(
            source_id="w1",
            machine_id=_MACHINE_A,
            day=date(2026, 8, 2),
            price=Decimal("50"),
        ),
    )
    findings = _detect(
        sales=sales,
        report_day=report_day,
        days_for_average=28,
        no_sales_habitual_max_nonempty=1,
        branch="today",
    )
    assert not any(isinstance(f, SalesMonitoringTodayNoSales) for f in findings)


def test_weekend_no_sales_emitted_when_history_above_habitual() -> None:
    report_day = date(2026, 8, 8)
    sales = (
        _sale(source_id="a", machine_id=_MACHINE_A, day=date(2026, 8, 1), price=Decimal("10")),
        _sale(source_id="b", machine_id=_MACHINE_A, day=date(2026, 8, 2), price=Decimal("20")),
    )
    findings = _detect(
        sales=sales,
        report_day=report_day,
        days_for_average=28,
        no_sales_habitual_max_nonempty=1,
        branch="yesterday",
    )
    assert any(isinstance(f, SalesMonitoringYesterdayNoSales) for f in findings)


def test_weekday_no_sales_remains_hard() -> None:
    report_day = date(2026, 8, 10)  # Monday
    findings = _detect(
        sales=(),
        report_day=report_day,
        days_for_average=28,
        no_sales_habitual_max_nonempty=1,
        branch="yesterday",
    )
    assert any(isinstance(f, SalesMonitoringYesterdayNoSales) for f in findings)


def test_habitual_nonempty_counts_null_price_sale_docs() -> None:
    report_day = date(2026, 8, 8)
    sales = (
        _sale(
            source_id="null-w",
            machine_id=_MACHINE_A,
            day=date(2026, 8, 2),
            price=None,
        ),
    )
    findings = _detect(
        sales=sales,
        report_day=report_day,
        days_for_average=28,
        no_sales_habitual_max_nonempty=0,
        branch="yesterday",
    )
    assert any(isinstance(f, SalesMonitoringYesterdayNoSales) for f in findings)


def test_decline_baseline_uses_only_like_day_weekdays() -> None:
    weekday_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    weekend_days = [date(2026, 7, d) for d in (18, 19)]
    sales = (
        tuple(
            _sale(
                source_id=f"wd-{d.isoformat()}",
                machine_id=_MACHINE_A,
                day=d,
                price=Decimal("100"),
                quantity=Decimal("100"),
            )
            for d in weekday_days
        )
        + tuple(
            _sale(
                source_id=f"we-{d.isoformat()}",
                machine_id=_MACHINE_A,
                day=d,
                price=Decimal("9999"),
                quantity=Decimal("9999"),
            )
            for d in weekend_days
        )
        + (
            _sale(
                source_id="r",
                machine_id=_MACHINE_A,
                day=_REPORT_DAY,
                price=Decimal("60"),
                quantity=Decimal("60"),
            ),
        )
    )
    findings = _detect(sales=sales, days_for_average=14)
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("100")
    assert declines[0].report_sum == Decimal("60")


def test_decline_excludes_empty_days_from_baseline() -> None:
    # Mon 2026-07-27; weekdays with money: 13–16; 17 Fri empty (no sale)
    days_with_money = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = tuple(
        _sale(
            source_id=f"b-{d.isoformat()}",
            machine_id=_MACHINE_A,
            day=d,
            price=Decimal("100"),
            quantity=Decimal("100"),
        )
        for d in days_with_money
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("60"),
            quantity=Decimal("60"),
        ),
    )
    findings = _detect(sales=sales, days_for_average=14)
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("100")


def test_decline_skipped_when_below_min_baseline_points() -> None:
    days = [date(2026, 7, d) for d in (13, 14, 15)]  # 3 weekday points
    sales = tuple(
        _sale(
            source_id=f"b-{d.isoformat()}",
            machine_id=_MACHINE_A,
            day=d,
            price=Decimal("100"),
            quantity=Decimal("100"),
        )
        for d in days
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("10"),
            quantity=Decimal("10"),
        ),
    )
    findings = _detect(
        sales=sales,
        days_for_average=14,
        baseline_min_points=4,
    )
    assert not any(isinstance(f, SalesMonitoringYesterdayDecline) for f in findings)


def test_decline_winsorize_clips_peak_n8_p10() -> None:
    days = [date(2026, 7, d) for d in (1, 2, 3, 6, 7, 8, 9, 10)]
    prices = [Decimal("10")] * 7 + [Decimal("100")]
    sales = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=price,
            quantity=price,
        )
        for day, price in zip(days, prices, strict=True)
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("5"),
            quantity=Decimal("5"),
        ),
    )
    findings = _detect(
        sales=sales,
        days_for_average=28,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("10")


def test_decline_mean_without_winsorize_below_min_points() -> None:
    days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    prices = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("100")]
    sales = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=price,
            quantity=price,
        )
        for day, price in zip(days, prices, strict=True)
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("5"),
            quantity=Decimal("5"),
        ),
    )
    findings = _detect(
        sales=sales,
        days_for_average=14,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("32.5")


def test_decline_winsorize_percent_zero_skips_clip() -> None:
    days = [date(2026, 7, d) for d in (1, 2, 3, 6, 7, 8, 9, 10)]
    prices = [Decimal("10")] * 7 + [Decimal("100")]
    sales = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=price,
            quantity=price,
        )
        for day, price in zip(days, prices, strict=True)
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("5"),
            quantity=Decimal("5"),
        ),
    )
    findings = _detect(
        sales=sales,
        days_for_average=28,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=0,
    )
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("21.25")


def test_decline_weekend_report_uses_only_weekend_points() -> None:
    report_day = date(2026, 7, 26)  # Sunday
    weekend_days = [date(2026, 7, d) for d in (12, 18, 19, 25)]  # Sun,Sat,Sun,Sat
    weekday_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = (
        tuple(
            _sale(
                source_id=f"we-{d.isoformat()}",
                machine_id=_MACHINE_A,
                day=d,
                price=Decimal("100"),
                quantity=Decimal("100"),
            )
            for d in weekend_days
        )
        + tuple(
            _sale(
                source_id=f"wd-{d.isoformat()}",
                machine_id=_MACHINE_A,
                day=d,
                price=Decimal("9999"),
                quantity=Decimal("9999"),
            )
            for d in weekday_days
        )
        + (
            _sale(
                source_id="r",
                machine_id=_MACHINE_A,
                day=report_day,
                price=Decimal("60"),
                quantity=Decimal("60"),
            ),
        )
    )
    findings = _detect(
        sales=sales,
        report_day=report_day,
        days_for_average=14,
        baseline_min_points=4,
    )
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("100")


def test_decline_drop_percent_is_measured_not_threshold() -> None:
    baseline_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=Decimal("761.4"),
            quantity=Decimal("761.4"),
        )
        for day in baseline_days
    ) + (
        _sale(
            source_id="r-471",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("471"),
            quantity=Decimal("471"),
        ),
    )
    findings = _detect(
        sales=sales,
        days_for_average=14,
        sales_drop_percent=30,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
    )
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].drop_percent == 38
    assert declines[0].report_sum == Decimal("471")
    assert declines[0].baseline_avg == Decimal("761.4")


def test_null_price_documents_are_not_no_sales() -> None:
    sales = (
        _sale(
            source_id="s1",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=None,
        ),
    )

    findings = _detect(sales=sales)

    assert not any(isinstance(f, SalesMonitoringYesterdayNoSales) for f in findings)


def test_decline_triggers_when_below_threshold() -> None:
    baseline_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales_decline = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=Decimal("100"),
            quantity=Decimal("100"),
        )
        for day in baseline_days
    ) + (
        _sale(
            source_id="r-60",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("60"),
            quantity=Decimal("60"),
        ),
    )
    decline_findings = _detect(sales=sales_decline, days_for_average=14)
    declines = [f for f in decline_findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].report_sum == Decimal("60")
    assert declines[0].baseline_avg == Decimal("100")
    assert declines[0].drop_percent == 40

    sales_ok = tuple(
        _sale(
            source_id=f"b2-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=Decimal("100"),
            quantity=Decimal("100"),
        )
        for day in baseline_days
    ) + (
        _sale(
            source_id="r-80",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("80"),
            quantity=Decimal("80"),
        ),
    )
    ok_findings = _detect(sales=sales_ok, days_for_average=14)
    assert not any(isinstance(f, SalesMonitoringYesterdayDecline) for f in ok_findings)


def test_decline_not_triggered_when_quantity_same_and_price_mix() -> None:
    weekday_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = tuple(
        _sale(
            source_id=f"b-{d.isoformat()}",
            machine_id=_MACHINE_A,
            day=d,
            price=Decimal("100"),
            quantity=Decimal("20"),
        )
        for d in weekday_days
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("1"),
            quantity=Decimal("20"),
        ),
    )
    findings = _detect(sales=sales, days_for_average=14)
    assert not any(isinstance(f, SalesMonitoringYesterdayDecline) for f in findings)


def test_decline_triggers_on_quantity_drop_not_price() -> None:
    weekday_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = tuple(
        _sale(
            source_id=f"b-{d.isoformat()}",
            machine_id=_MACHINE_A,
            day=d,
            price=Decimal("1"),
            quantity=Decimal("20"),
        )
        for d in weekday_days
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("100"),
            quantity=Decimal("12"),
        ),
    )
    findings = _detect(sales=sales, days_for_average=14)
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].report_sum == Decimal("12")
    assert declines[0].baseline_avg == Decimal("20")
    assert declines[0].drop_percent == 40


def test_decline_includes_null_price_days_with_positive_qty() -> None:
    weekday_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = tuple(
        _sale(
            source_id=f"b-{d.isoformat()}",
            machine_id=_MACHINE_A,
            day=d,
            price=None,
            quantity=Decimal("20"),
        )
        for d in weekday_days
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=None,
            quantity=Decimal("12"),
        ),
    )
    findings = _detect(sales=sales, days_for_average=14)
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].report_sum == Decimal("12")
    assert declines[0].baseline_avg == Decimal("20")


def test_decline_excludes_zero_qty_days_from_baseline() -> None:
    days_with_qty = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    zero_qty_day = date(2026, 7, 17)
    sales = tuple(
        _sale(
            source_id=f"b-{d.isoformat()}",
            machine_id=_MACHINE_A,
            day=d,
            price=Decimal("20"),
            quantity=Decimal("20"),
        )
        for d in days_with_qty
    ) + (
        _sale(
            source_id="zero",
            machine_id=_MACHINE_A,
            day=zero_qty_day,
            price=Decimal("9999"),
            quantity=Decimal("0"),
        ),
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("12"),
            quantity=Decimal("12"),
        ),
    )
    findings = _detect(sales=sales, days_for_average=14)
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("20")
    assert declines[0].report_sum == Decimal("12")


def test_decline_winsorize_clips_qty_peak_when_prices_flat() -> None:
    days = [date(2026, 7, d) for d in (1, 2, 3, 6, 7, 8, 9, 10)]
    quantities = [Decimal("10")] * 7 + [Decimal("100")]
    sales = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=Decimal("50"),
            quantity=qty,
        )
        for day, qty in zip(days, quantities, strict=True)
    ) + (
        _sale(
            source_id="r",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("50"),
            quantity=Decimal("5"),
        ),
    )
    findings = _detect(
        sales=sales,
        days_for_average=28,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
    )
    declines = [f for f in findings if isinstance(f, SalesMonitoringYesterdayDecline)]
    assert len(declines) == 1
    assert declines[0].baseline_avg == Decimal("10")
    assert declines[0].report_sum == Decimal("5")


def test_at_most_one_finding_per_event_type_machine_day() -> None:
    findings_once = _detect(sales=())
    findings_twice = _detect(sales=())
    assert len(findings_once) == 1
    assert isinstance(findings_once[0], SalesMonitoringYesterdayNoSales)
    keys_once = {(type(f).__name__, f.machine_id, f.report_day) for f in findings_once}
    keys_twice = {(type(f).__name__, f.machine_id, f.report_day) for f in findings_twice}
    assert keys_once == keys_twice
    assert len(keys_once) == len(findings_once)
    expected_id = sales_finding_event_id(
        event_type="SalesMonitoringYesterdayNoSales",
        machine_id=_MACHINE_A,
        report_day=_REPORT_DAY,
    )
    assert findings_once[0].event_id == expected_id


def test_excluded_machine_not_in_findings() -> None:
    findings = _detect(
        sales=(),
        catalog_machine_ids=(_MACHINE_A, _MACHINE_B),
        excluded_codes=frozenset({_MACHINE_A.value}),
        branch="today",
    )
    assert len(findings) == 1
    assert isinstance(findings[0], SalesMonitoringTodayNoSales)
    assert findings[0].machine_id == _MACHINE_B


def test_detect_excludes_ui_flag_false() -> None:
    findings = _detect(
        sales=(),
        catalog_machine_ids=(_MACHINE_A, _MACHINE_B),
        excluded_codes=union_excluded_machine_codes(
            frozenset(),
            frozenset({_MACHINE_A.value}),
        ),
        branch="yesterday",
    )
    no_sales_ids = {
        f.machine_id for f in findings if isinstance(f, SalesMonitoringYesterdayNoSales)
    }
    assert _MACHINE_A not in no_sales_ids
    assert _MACHINE_B in no_sales_ids


def test_today_branch_does_not_emit_decline() -> None:
    baseline_days = [date(2026, 7, d) for d in (13, 14, 15, 16)]
    sales = tuple(
        _sale(
            source_id=f"b-{day.isoformat()}",
            machine_id=_MACHINE_A,
            day=day,
            price=Decimal("100"),
            quantity=Decimal("100"),
        )
        for day in baseline_days
    ) + (
        _sale(
            source_id="r-60",
            machine_id=_MACHINE_A,
            day=_REPORT_DAY,
            price=Decimal("60"),
            quantity=Decimal("60"),
        ),
    )

    findings = _detect(sales=sales, days_for_average=14, branch="today")

    assert not any(isinstance(f, SalesMonitoringYesterdayDecline) for f in findings)
    assert not any(isinstance(f, SalesMonitoringTodayNoSales) for f in findings)
