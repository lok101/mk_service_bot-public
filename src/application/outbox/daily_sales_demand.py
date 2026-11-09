from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.inventory_reconciliation import (
    IngestCursorNotReady,
    SellableCatalogNotReady,
)
from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.domain.events import DomainEvent
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested


@runtime_checkable
class CreateDailySalesDemandsPort(Protocol):
    async def execute(self, *, sales_day: date) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class DailySalesDemandHandler:
    create_demands: CreateDailySalesDemandsPort
    not_ready_retry_minutes: int
    not_ready_max_attempts: int

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, DailySalesDemandRequested):
            raise NonRetryableOutboxError(
                f"Unsupported daily sales demand event: {type(event).__name__}",
            )
        try:
            await self.create_demands.execute(sales_day=event.sales_day)
        except (IngestCursorNotReady, SellableCatalogNotReady) as pending:
            raise DeferredRetryOutboxError(
                str(pending),
                delay=timedelta(minutes=self.not_ready_retry_minutes),
                max_attempts=self.not_ready_max_attempts,
            ) from pending


__all__ = [
    "CreateDailySalesDemandsPort",
    "DAILY_SALES_DEMAND_HANDLER_ID",
    "DailySalesDemandHandler",
]
