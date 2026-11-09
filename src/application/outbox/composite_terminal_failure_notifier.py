from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.machine_pnl.opex_ports import MachinePnlOpsTerminalAlerter
from src.application.outbox.daily_sales_demand_ops_ports import (
    DailySalesDemandOpsTerminalAlerter,
)
from src.application.outbox.handler_ids import (
    DAILY_SALES_DEMAND_HANDLER_ID,
    MACHINE_PNL_PERIOD_HANDLER_ID,
)
from src.application.outbox.ports import OutboxEventDeserializer
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.domain.machine_pnl.events import MachinePeriodPnlRequested

logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class CompositeOutboxTerminalFailureNotifier:
    """FormWorkflow terminal notifier + machine_pnl / daily_sales_demand ops TG on exhaust."""

    primary: OutboxTerminalFailureNotifier
    machine_pnl_ops: MachinePnlOpsTerminalAlerter
    daily_sales_demand_ops: DailySalesDemandOpsTerminalAlerter
    event_deserializer: OutboxEventDeserializer

    @beartype
    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        await self.primary.notify_terminal_failure(
            handler_id=handler_id,
            event_document=event_document,
            error_message=error_message,
            entry_id=entry_id,
            claim_id=claim_id,
        )
        if handler_id == MACHINE_PNL_PERIOD_HANDLER_ID:
            period_id: str | None = None
            event_id: str | None = None
            try:
                event = self.event_deserializer.from_document(event_document)
            except Exception:
                logger.error(
                    "machine_pnl ops terminal notify: could not deserialize event: %s",
                    error_message,
                )
            else:
                if isinstance(event, MachinePeriodPnlRequested):
                    period_id = event.period_id
                    event_id = event.event_id.value

            self.machine_pnl_ops.notify_terminal_failure(
                handler_id=handler_id,
                error_message=error_message,
                period_id=period_id,
                event_id=event_id,
            )
            return

        if handler_id != DAILY_SALES_DEMAND_HANDLER_ID:
            return

        sales_day: str | None = None
        event_id_daily: str | None = None
        try:
            daily_event = self.event_deserializer.from_document(event_document)
        except Exception:
            logger.error(
                "daily_sales_demand ops terminal notify: could not deserialize event: %s",
                error_message,
            )
        else:
            if isinstance(daily_event, DailySalesDemandRequested):
                sales_day = daily_event.sales_day.isoformat()
                event_id_daily = daily_event.event_id.value

        self.daily_sales_demand_ops.notify_terminal_failure(
            handler_id=handler_id,
            error_message=error_message,
            sales_day=sales_day,
            event_id=event_id_daily,
        )
