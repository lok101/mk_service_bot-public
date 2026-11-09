from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.sales_monitoring.ports import SalesMonitoringAuditStore
from src.domain.events import DomainEvent
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)

_SUPPORTED_EVENTS = (
    SalesMonitoringYesterdayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringTodayNoSales,
    SalesMonitoringOfflineOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringNoSalesStaleCleared,
)


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringAuditHandler:
    audit_store: SalesMonitoringAuditStore

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, _SUPPORTED_EVENTS):
            raise NonRetryableOutboxError(
                f"Unsupported sales monitoring audit event: {type(event).__name__}",
            )
        self.audit_store.upsert_from_event(event)
