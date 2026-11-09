from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.sales_monitoring.detect_sales_findings import (
    ReportBranch,
    SalesFinding,
    detect_sales_findings,
)
from src.application.sales_monitoring.format_report import (
    ReportDeclineLine,
    format_decline_sales_report,
)
from src.application.sales_monitoring.ports import (
    DomainEventPublisher,
    LastMaintenanceByMachine,
    OutboxHandlerDrainer,
    SalesForReportLoader,
    SalesMonitoringDeclineReportNotifier,
    TechnicianDisplayLookup,
)
from src.application.sales_monitoring.run_offline_poll import (
    SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS,
    drain_handler_until_empty,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringYesterdayDecline,
)


class EmptyCatalogError(ValueError):
    """Report job cannot run without a non-empty machine catalog."""


@beartype
@dataclass(frozen=True, slots=True)
class CatalogMachine:
    machine_id: MachineId
    name: str
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None


@beartype
def _enrich_finding(
    finding: SalesFinding,
    *,
    catalog_by_id: dict[MachineId, CatalogMachine],
    last_maintenance: LastMaintenanceByMachine,
    technician_display: TechnicianDisplayLookup,
) -> SalesFinding:
    entry = catalog_by_id[finding.machine_id]
    snapshot = last_maintenance.get(finding.machine_id)
    last_id = snapshot.technician_id if snapshot is not None else None
    last_display = technician_display.display_name(last_id) if last_id is not None else None
    last_at = snapshot.completed_at if snapshot is not None else None
    return replace(
        finding,
        assigned_technician_id=entry.assigned_technician_id,
        assigned_technician_display=entry.assigned_technician_display,
        last_serviced_by_technician_id=last_id,
        last_serviced_by_display=last_display,
        last_serviced_at=last_at,
    )


@beartype
@dataclass(frozen=True, slots=True)
class RunSalesReport:
    sales_loader: SalesForReportLoader
    last_maintenance: LastMaintenanceByMachine
    technician_display: TechnicianDisplayLookup
    publisher: DomainEventPublisher
    drainer: OutboxHandlerDrainer
    decline_notifier: SalesMonitoringDeclineReportNotifier

    @beartype
    def execute(
        self,
        *,
        catalog: Sequence[CatalogMachine],
        excluded_codes: frozenset[str],
        report_day: date,
        branch: ReportBranch,
        now: datetime,
        timezone: ZoneInfo,
        days_for_average: int,
        sales_drop_percent: int,
        sales_lookback_days: int,
        baseline_min_points: int,
        baseline_winsorize_min_points: int,
        baseline_winsorize_percent: int,
        no_sales_habitual_max_nonempty: int,
    ) -> str:
        if not catalog:
            raise EmptyCatalogError("Sales monitoring catalog is empty")

        catalog_by_id = {entry.machine_id: entry for entry in catalog}
        machine_ids = tuple(entry.machine_id for entry in catalog)

        window_start = datetime.combine(
            report_day - timedelta(days=sales_lookback_days),
            time.min,
            tzinfo=timezone,
        )
        window_end = datetime.combine(report_day + timedelta(days=1), time.min, tzinfo=timezone)
        sales = self.sales_loader.load_for_report(
            machine_ids=machine_ids,
            opened_at=window_start,
            closed_at=window_end,
        )

        findings = detect_sales_findings(
            catalog_machine_ids=machine_ids,
            excluded_codes=excluded_codes,
            sales=sales,
            report_day=report_day,
            timezone=timezone,
            days_for_average=days_for_average,
            sales_drop_percent=sales_drop_percent,
            baseline_min_points=baseline_min_points,
            baseline_winsorize_min_points=baseline_winsorize_min_points,
            baseline_winsorize_percent=baseline_winsorize_percent,
            no_sales_habitual_max_nonempty=no_sales_habitual_max_nonempty,
            branch=branch,
            occurred_at=now,
        )
        enriched = tuple(
            _enrich_finding(
                finding,
                catalog_by_id=catalog_by_id,
                last_maintenance=self.last_maintenance,
                technician_display=self.technician_display,
            )
            for finding in findings
        )

        for event in enriched:
            self.publisher.publish(event)
        if enriched:
            for handler_id in SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS:
                drain_handler_until_empty(self.drainer, handler_id)

        decline_text = ""
        if branch == "yesterday":
            decline_lines = tuple(
                ReportDeclineLine(
                    machine_id=event.machine_id,
                    machine_name=catalog_by_id[event.machine_id].name,
                    technician_display=event.assigned_technician_display,
                    report_sum=event.report_sum,
                    baseline_avg=event.baseline_avg,
                    drop_percent=event.drop_percent,
                )
                for event in enriched
                if isinstance(event, SalesMonitoringYesterdayDecline)
            )
            decline_text = format_decline_sales_report(
                declines=decline_lines,
                report_day=report_day,
            )
            self.decline_notifier.send_decline_report(decline_text)
        return decline_text
