from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.application.outbox import DAILY_SALES_DEMAND_HANDLER_ID
from src.infrastructure.daily_sales_demand.enqueue_daily_sales_demand import (
    compute_yesterday_sales_day,
    enqueue_daily_sales_demand_for_day,
)
from src.infrastructure.outbox.memory import InMemoryOutboxStore


def test_cron_enqueues_yesterday_sales_day() -> None:
    tz = ZoneInfo("Europe/Moscow")
    assert compute_yesterday_sales_day(
        now=datetime(2026, 8, 10, 4, 0, tzinfo=tz),
        tz=tz,
    ) == date(2026, 8, 9)


def test_enqueue_writes_stable_event_id() -> None:
    store = InMemoryOutboxStore(max_attempts=5)
    occurred_at = datetime(2026, 8, 10, 4, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    inserted = enqueue_daily_sales_demand_for_day(
        outbox=store,
        sales_day=date(2026, 8, 9),
        occurred_at=occurred_at,
    )
    assert inserted is True
    assert (
        enqueue_daily_sales_demand_for_day(
            outbox=store,
            sales_day=date(2026, 8, 9),
            occurred_at=occurred_at,
        )
        is False
    )
    entries = list(store._entries.values())
    assert len(entries) == 1
    assert entries[0]["event_id"] == "daily_sales_demand:2026-08-09"
    assert entries[0]["handler_id"] == DAILY_SALES_DEMAND_HANDLER_ID
