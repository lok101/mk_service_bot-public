from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.sales_monitoring.qty_baseline import (
    _daily_qty,
    _like_day_class,
    like_day_qty_baseline_avg,
)
from src.domain.calendar import calendar_day_in_timezone
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.domain.sales_monitoring.event_ids import sales_finding_event_id
from src.domain.sales_monitoring.events import (
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)

SalesFinding = (
    SalesMonitoringYesterdayNoSales | SalesMonitoringYesterdayDecline | SalesMonitoringTodayNoSales
)

ReportBranch = Literal["yesterday", "today"]


@beartype
def detect_sales_findings(
    *,
    catalog_machine_ids: Sequence[MachineId],
    excluded_codes: frozenset[str],
    sales: Sequence[MachineSale],
    report_day: date,
    timezone: ZoneInfo,
    days_for_average: int,
    sales_drop_percent: int,
    baseline_min_points: int,
    baseline_winsorize_min_points: int,
    baseline_winsorize_percent: int,
    branch: ReportBranch,
    occurred_at: datetime,
    no_sales_habitual_max_nonempty: int = 1,
) -> list[SalesFinding]:
    """Pure detection: catalog − exclude → no_sales / decline findings (null snapshots)."""
    active = [mid for mid in catalog_machine_ids if mid.value not in excluded_codes]
    sales_by_machine_day = _index_sales_by_machine_day(sales, timezone)

    findings: list[SalesFinding] = []
    for machine_id in active:
        by_day = sales_by_machine_day.get(machine_id, {})
        report_sales = by_day.get(report_day, ())

        if not report_sales:
            if _is_habitual_quiet_weekend(
                report_day=report_day,
                by_day=by_day,
                days_for_average=days_for_average,
                max_nonempty=no_sales_habitual_max_nonempty,
            ):
                pass  # skip no_sales
            else:
                findings.append(
                    _no_sales_event(
                        branch=branch,
                        machine_id=machine_id,
                        report_day=report_day,
                        occurred_at=occurred_at,
                    )
                )

        if branch == "yesterday":
            decline = _maybe_decline(
                machine_id=machine_id,
                report_day=report_day,
                by_day=by_day,
                days_for_average=days_for_average,
                sales_drop_percent=sales_drop_percent,
                baseline_min_points=baseline_min_points,
                baseline_winsorize_min_points=baseline_winsorize_min_points,
                baseline_winsorize_percent=baseline_winsorize_percent,
                occurred_at=occurred_at,
            )
            if decline is not None:
                findings.append(decline)

    return findings


def _is_habitual_quiet_weekend(
    *,
    report_day: date,
    by_day: Mapping[date, Sequence[MachineSale]],
    days_for_average: int,
    max_nonempty: int,
) -> bool:
    if _like_day_class(report_day) != "weekend":
        return False
    nonempty = 0
    for offset in range(1, days_for_average + 1):
        day = report_day - timedelta(days=offset)
        if _like_day_class(day) != "weekend":
            continue
        if by_day.get(day, ()):
            nonempty += 1
    return nonempty <= max_nonempty


def _index_sales_by_machine_day(
    sales: Sequence[MachineSale],
    timezone: ZoneInfo,
) -> dict[MachineId, dict[date, list[MachineSale]]]:
    indexed: dict[MachineId, dict[date, list[MachineSale]]] = {}
    for sale in sales:
        day = calendar_day_in_timezone(sale.occurred_at, timezone)
        indexed.setdefault(sale.machine_id, {}).setdefault(day, []).append(sale)
    return indexed


def _no_sales_event(
    *,
    branch: ReportBranch,
    machine_id: MachineId,
    report_day: date,
    occurred_at: datetime,
) -> SalesMonitoringYesterdayNoSales | SalesMonitoringTodayNoSales:
    if branch == "today":
        event_type = "SalesMonitoringTodayNoSales"
        return SalesMonitoringTodayNoSales(
            event_id=sales_finding_event_id(
                event_type=event_type,
                machine_id=machine_id,
                report_day=report_day,
            ),
            machine_id=machine_id,
            report_day=report_day,
            occurred_at=occurred_at,
            assigned_technician_id=None,
            assigned_technician_display=None,
            last_serviced_by_technician_id=None,
            last_serviced_by_display=None,
            last_serviced_at=None,
        )
    event_type = "SalesMonitoringYesterdayNoSales"
    return SalesMonitoringYesterdayNoSales(
        event_id=sales_finding_event_id(
            event_type=event_type,
            machine_id=machine_id,
            report_day=report_day,
        ),
        machine_id=machine_id,
        report_day=report_day,
        occurred_at=occurred_at,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _maybe_decline(
    *,
    machine_id: MachineId,
    report_day: date,
    by_day: Mapping[date, Sequence[MachineSale]],
    days_for_average: int,
    sales_drop_percent: int,
    baseline_min_points: int,
    baseline_winsorize_min_points: int,
    baseline_winsorize_percent: int,
    occurred_at: datetime,
) -> SalesMonitoringYesterdayDecline | None:
    report_sum = _daily_qty(by_day.get(report_day, ()))
    if report_sum is None:
        return None

    baseline_avg = like_day_qty_baseline_avg(
        report_day=report_day,
        by_day=by_day,
        days_for_average=days_for_average,
        baseline_min_points=baseline_min_points,
        baseline_winsorize_min_points=baseline_winsorize_min_points,
        baseline_winsorize_percent=baseline_winsorize_percent,
    )
    if baseline_avg is None:
        return None

    threshold = baseline_avg * (Decimal("1") - Decimal(sales_drop_percent) / Decimal("100"))
    if report_sum >= threshold:
        return None

    actual_drop = (Decimal("1") - report_sum / baseline_avg) * Decimal("100")
    drop_percent = int(actual_drop.to_integral_value(rounding=ROUND_HALF_UP))

    event_type = "SalesMonitoringYesterdayDecline"
    return SalesMonitoringYesterdayDecline(
        event_id=sales_finding_event_id(
            event_type=event_type,
            machine_id=machine_id,
            report_day=report_day,
        ),
        machine_id=machine_id,
        report_day=report_day,
        occurred_at=occurred_at,
        report_sum=report_sum,
        baseline_avg=baseline_avg,
        drop_percent=drop_percent,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
