from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import OutboxStore
from src.application.outbox import DAILY_SALES_DEMAND_HANDLER_ID
from src.infrastructure.daily_sales_demand.drain import (
    OutboxHandlerDrainer,
    drain_handler_until_empty,
)
from src.infrastructure.daily_sales_demand.enqueue_daily_sales_demand import (
    compute_yesterday_sales_day,
    enqueue_daily_sales_demand_for_day,
)


@beartype
def run_daily_sales_demand_tick(
    *,
    outbox: OutboxStore,
    drainer: OutboxHandlerDrainer,
    now: datetime,
    tz: ZoneInfo,
) -> None:
    sales_day = compute_yesterday_sales_day(now=now, tz=tz)
    enqueue_daily_sales_demand_for_day(
        outbox=outbox,
        sales_day=sales_day,
        occurred_at=now,
    )
    drain_handler_until_empty(drainer, DAILY_SALES_DEMAND_HANDLER_ID)
