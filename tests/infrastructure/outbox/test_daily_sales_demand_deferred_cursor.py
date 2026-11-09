from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from src.application.form_submissions.outbox_errors import DeferredRetryOutboxError
from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.domain.ids import EventId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.infrastructure.outbox.memory import (
    OUTBOX_STATUS_PENDING,
    InMemoryOutboxStore,
)
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker

_EVENT = DailySalesDemandRequested(
    event_id=EventId("daily_sales_demand:2026-10-08"),
    sales_day=date(2026, 10, 8),
    occurred_at=datetime(2026, 10, 9, 4, 0, tzinfo=UTC),
)


def test_demand_deferred_retry_survives_default_outbox_max_attempts_horizon() -> None:
    """Cursor-not-ready deferred override keeps entry pending past OUTBOX_MAX_ATTEMPTS=5."""
    asyncio.run(_test_demand_deferred_retry_survives_default_outbox_max_attempts_horizon())


async def _test_demand_deferred_retry_survives_default_outbox_max_attempts_horizon() -> None:
    store = InMemoryOutboxStore(max_attempts=5)

    async def _deferred_handler(event: object) -> None:
        raise DeferredRetryOutboxError(
            "global_cursor not ready for day_end",
            delay=timedelta(minutes=15),
            max_attempts=48,
        )

    processors = OutboxProcessorRegistry()
    processors.register(DAILY_SALES_DEMAND_HANDLER_ID, _deferred_handler)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    worker = OutboxWorker(store=store, processors=processors)
    for _ in range(5):
        entry = next(iter(store._entries.values()))
        entry["next_retry_at"] = datetime.now(tz=UTC) - timedelta(seconds=1)
        entry["status"] = OUTBOX_STATUS_PENDING
        await worker.process_batch()

    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 5
