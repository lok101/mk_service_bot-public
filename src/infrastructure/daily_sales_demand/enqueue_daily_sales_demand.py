from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import OutboxStore
from src.application.outbox import DAILY_SALES_DEMAND_HANDLER_ID
from src.domain.inventory_reconciliation.events import (
    DailySalesDemandRequested,
    daily_sales_demand_event_id,
)
from src.infrastructure.outbox.serialization import event_to_outbox_document

_LOGGER = logging.getLogger(__name__)


@beartype
def compute_yesterday_sales_day(*, now: datetime, tz: ZoneInfo) -> date:
    local_now = now.astimezone(tz)
    return local_now.date() - timedelta(days=1)


@beartype
def enqueue_daily_sales_demand_for_day(
    *,
    outbox: OutboxStore,
    sales_day: date,
    occurred_at: datetime,
) -> bool:
    event = DailySalesDemandRequested(
        event_id=daily_sales_demand_event_id(sales_day),
        sales_day=sales_day,
        occurred_at=occurred_at,
    )
    event_document = event_to_outbox_document(event)
    inserted = outbox.enqueue(
        event_id=event.event_id.value,
        handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
        event_document=event_document,
    )
    _LOGGER.info(
        "daily_sales_demand enqueue sales_day=%s inserted=%s",
        sales_day.isoformat(),
        inserted,
    )
    return inserted
