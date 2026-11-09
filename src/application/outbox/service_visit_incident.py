from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.sales_monitoring.no_sales_control import NoSalesVisitBlockLookup
from src.application.service_visits import (
    ClearNoSalesIncident,
    ClearOfflineIncident,
    EnqueueVisitForceNotify,
    IncidentSource,
    OpenServiceIncident,
    no_sales_incident_visit_id,
)
from src.domain.calendar import operational_day
from src.domain.events import DomainEvent
from src.domain.sales_monitoring import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)

_DAY_NO_SALES_EVENTS = (SalesMonitoringYesterdayNoSales, SalesMonitoringTodayNoSales)


@beartype
@dataclass(frozen=True, slots=True)
class ServiceVisitIncidentHandler:
    opener: OpenServiceIncident
    clearer: ClearOfflineIncident
    no_sales_clearer: ClearNoSalesIncident
    timezone: ZoneInfo
    day_end_hour: int
    force_notify: EnqueueVisitForceNotify | None = None
    control: NoSalesVisitBlockLookup | None = None

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if isinstance(event, SalesMonitoringYesterdayDecline):
            return
        if isinstance(event, SalesMonitoringOfflineOpened):
            return
        if isinstance(event, SalesMonitoringOfflineCleared):
            self.clearer.execute(
                opened_event_id=event.opened_event_id,
                machine_id=event.machine_id,
                now=event.occurred_at,
            )
            return
        if isinstance(event, _DAY_NO_SALES_EVENTS):
            return
        if isinstance(event, SalesMonitoringNoSalesStaleCleared):
            self.no_sales_clearer.execute(
                machine_id=event.machine_id,
                now=event.occurred_at,
            )
            return
        if isinstance(event, SalesMonitoringNoSalesStaleOpened):
            if self.control is not None and self.control.blocks_technician_visit(
                machine_id=event.machine_id,
                opened_event_id=event.event_id.value,
            ):
                return
            report_day = event.occurred_at.astimezone(self.timezone).date()
            if self.opener.would_suppress_no_sales(
                machine_id=event.machine_id,
                report_day=report_day,
            ):
                self.no_sales_clearer.execute(
                    machine_id=event.machine_id,
                    now=event.occurred_at,
                )
                return
            result = self.opener.execute(
                machine_id=event.machine_id,
                ops_day=operational_day(event.occurred_at, self.timezone, self.day_end_hour),
                source=IncidentSource.NO_SALES,
                visit_id=no_sales_incident_visit_id(event.machine_id),
                now=event.occurred_at,
                report_day=report_day,
            )
            if self.control is not None and self.control.blocks_technician_visit(
                machine_id=event.machine_id,
                opened_event_id=event.event_id.value,
            ):
                self.no_sales_clearer.execute(
                    machine_id=event.machine_id,
                    now=event.occurred_at,
                )
                return
            if self.force_notify is not None:
                self.force_notify.execute(
                    result=result,
                    incident_source=IncidentSource.NO_SALES,
                    occurred_at=event.occurred_at,
                )
            return
        raise NonRetryableOutboxError(
            f"Unsupported event: {type(event).__name__}",
        )
