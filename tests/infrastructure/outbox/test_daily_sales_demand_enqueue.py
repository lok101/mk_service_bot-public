from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.domain.ids import EventId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.outbox.serialization import event_to_outbox_document


def test_enqueue_idempotent_same_day() -> None:
    store = InMemoryOutboxStore(max_attempts=5)
    event = DailySalesDemandRequested(
        event_id=EventId("daily_sales_demand:2026-08-09"),
        sales_day=date(2026, 8, 9),
        occurred_at=datetime(2026, 8, 10, 4, 0, tzinfo=UTC),
    )
    doc = event_to_outbox_document(event)
    assert (
        store.enqueue(
            event_id="daily_sales_demand:2026-08-09",
            handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
            event_document=doc,
        )
        is True
    )
    assert (
        store.enqueue(
            event_id="daily_sales_demand:2026-08-09",
            handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
            event_document=doc,
        )
        is False
    )
