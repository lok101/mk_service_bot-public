from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from src.application.form_submissions.outbox_errors import DeferredRetryOutboxError
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.outbox.memory import (
    OUTBOX_STATUS_PENDING,
    InMemoryOutboxStore,
)
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker

_HANDLER_ID = "machine_pnl_period"
_EVENT = RevisionCompleted(
    event_id=EventId("event-deferred-1"),
    revision_id=RevisionId("rev-1"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    completed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    source=RevisionSource.GOOGLE_FORM,
    form_id="form-1",
    form_token="token-1",
)


def test_outbox_worker_deferred_retry_error_sets_long_delay() -> None:
    asyncio.run(_test_outbox_worker_deferred_retry_error_sets_long_delay())


async def _test_outbox_worker_deferred_retry_error_sets_long_delay() -> None:
    store = InMemoryOutboxStore(max_attempts=2)

    async def _deferred_handler(event: object) -> None:
        raise DeferredRetryOutboxError(
            "rent pending",
            delay=timedelta(hours=24),
            max_attempts=7,
        )

    processors = OutboxProcessorRegistry()
    processors.register(_HANDLER_ID, _deferred_handler)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    before = datetime.now(tz=UTC)
    worker = OutboxWorker(store=store, processors=processors)
    await worker.process_batch()

    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 1
    delta = entry["next_retry_at"] - before
    assert timedelta(hours=23, minutes=50) <= delta <= timedelta(hours=24, minutes=10)
