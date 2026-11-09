from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime, timedelta

from src.application.form_submissions.outbox_errors import UnknownProductNamesError
from src.application.outbox.handler_ids import REVISION_TELEGRAM_HANDLER_ID
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.outbox.memory import (
    OUTBOX_STATUS_FAILED,
    OUTBOX_STATUS_PENDING,
    OUTBOX_STATUS_PROCESSED,
    InMemoryOutboxStore,
)
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker

_EVENT = RevisionCompleted(
    event_id=EventId("event-outbox-1"),
    revision_id=RevisionId("rev-1"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    completed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    source=RevisionSource.GOOGLE_FORM,
    form_id="form-1",
    form_token="token-1",
)


def test_outbox_deferred_retry_uses_handler_delay_hours() -> None:
    store = InMemoryOutboxStore(max_attempts=5)
    document = event_to_outbox_document(_EVENT)
    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id="machine_pnl_period",
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    entry_id = claimed[0]["entry_id"]
    claim_id = claimed[0]["claim_id"]
    before = datetime.now(tz=UTC)
    terminal = store.mark_failed(
        entry_id,
        claim_id=claim_id,
        error_message="rent pending",
        retry_delay=timedelta(hours=24),
        max_attempts_override=7,
    )
    assert terminal is False
    entry = store._entries[entry_id]
    assert entry["status"] == OUTBOX_STATUS_PENDING
    delta = entry["next_retry_at"] - before
    assert timedelta(hours=23, minutes=50) <= delta <= timedelta(hours=24, minutes=10)


def test_outbox_mark_failed_without_retry_delay_keeps_short_backoff() -> None:
    store = InMemoryOutboxStore(max_attempts=5)
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id="h1",
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    before = datetime.now(tz=UTC)
    store.mark_failed(
        claimed[0]["entry_id"],
        claim_id=claimed[0]["claim_id"],
        error_message="transient",
    )
    entry = store._entries[claimed[0]["entry_id"]]
    delta = entry["next_retry_at"] - before
    assert delta <= timedelta(seconds=60)


def test_outbox_enqueue_is_idempotent_by_event_and_handler() -> None:
    store = InMemoryOutboxStore()
    document = event_to_outbox_document(_EVENT)

    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    assert not store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )


def test_outbox_processor_offloads_sync_handler_off_event_loop() -> None:
    # edge: sync Kit/HTTP handler (shop_list_publish) must not freeze admin HTTP
    processors = OutboxProcessorRegistry()
    ran: list[str] = []
    ticks_during_handler = 0

    def _blocking_sync_handler(event: object) -> None:
        assert isinstance(event, RevisionCompleted)
        time.sleep(0.2)
        ran.append(event.event_id.value)

    processors.register(REVISION_TELEGRAM_HANDLER_ID, _blocking_sync_handler)

    async def run_both() -> None:
        nonlocal ticks_during_handler

        async def ticker() -> None:
            nonlocal ticks_during_handler
            while True:
                await asyncio.sleep(0.01)
                ticks_during_handler += 1

        ticker_task = asyncio.create_task(ticker())
        try:
            await processors.process(REVISION_TELEGRAM_HANDLER_ID, _EVENT)
        finally:
            ticker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker_task

    asyncio.run(run_both())

    assert ran == [_EVENT.event_id.value]
    # If sync handler ran on the event loop, ticker could not advance during sleep(0.2).
    assert ticks_during_handler >= 5


def test_outbox_worker_processes_revision_telegram_handler() -> None:
    asyncio.run(_test_outbox_worker_processes_revision_telegram_handler())


async def _test_outbox_worker_processes_revision_telegram_handler() -> None:
    store = InMemoryOutboxStore()
    processed_event_ids: list[str] = []

    async def _handler(event: object) -> None:
        assert isinstance(event, RevisionCompleted)
        processed_event_ids.append(event.event_id.value)

    processors = OutboxProcessorRegistry()
    processors.register(REVISION_TELEGRAM_HANDLER_ID, _handler)

    publisher = OutboxDomainEventPublisher(store=store)
    publisher.subscribe(RevisionCompleted, REVISION_TELEGRAM_HANDLER_ID)
    publisher.publish(_EVENT)

    worker = OutboxWorker(store=store, processors=processors)
    processed_count = await worker.process_batch()

    assert processed_count == 1
    assert processed_event_ids == [_EVENT.event_id.value]
    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PROCESSED


def test_outbox_worker_retries_then_marks_failed() -> None:
    asyncio.run(_test_outbox_worker_retries_then_marks_failed())


async def _test_outbox_worker_retries_then_marks_failed() -> None:
    store = InMemoryOutboxStore(max_attempts=2)
    attempts = 0

    async def _failing_handler(event: object) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("simulated handler failure")

    processors = OutboxProcessorRegistry()
    processors.register(REVISION_TELEGRAM_HANDLER_ID, _failing_handler)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    worker = OutboxWorker(store=store, processors=processors)
    await worker.process_batch()
    entry = next(iter(store._entries.values()))
    entry["next_retry_at"] = datetime.now(tz=UTC) - timedelta(seconds=1)
    await worker.process_batch()

    assert attempts == 2
    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_FAILED
    assert entry["attempts"] == 2


def test_outbox_worker_requeues_failed_entry_for_retry() -> None:
    asyncio.run(_test_outbox_worker_requeues_failed_entry_for_retry())


async def _test_outbox_worker_requeues_failed_entry_for_retry() -> None:
    store = InMemoryOutboxStore(max_attempts=3)
    attempts = 0

    async def _flaky_handler(event: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("temporary failure")

    processors = OutboxProcessorRegistry()
    processors.register(REVISION_TELEGRAM_HANDLER_ID, _flaky_handler)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    worker = OutboxWorker(store=store, processors=processors)
    await worker.process_batch()
    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 1
    entry["next_retry_at"] = datetime.now(tz=UTC) - timedelta(seconds=1)

    await worker.process_batch()
    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PROCESSED
    assert attempts == 2


def test_in_memory_outbox_reclaim_stuck_processing() -> None:
    store = InMemoryOutboxStore(processing_lease_seconds=0)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )
    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    assert isinstance(claimed[0]["claim_id"], str)
    stale_claim_id = str(claimed[0]["claim_id"])
    entry_id = str(claimed[0]["entry_id"])

    reclaimed = store.reclaim_stuck_processing()
    assert reclaimed == 1

    claimed_again = store.claim_pending(limit=1)
    assert len(claimed_again) == 1
    assert claimed_again[0]["claim_id"] != stale_claim_id

    assert not store.mark_processed(entry_id, claim_id=stale_claim_id)
    assert store.mark_processed(entry_id, claim_id=str(claimed_again[0]["claim_id"]))


def test_outbox_worker_marks_unknown_products_as_permanent_failure() -> None:
    asyncio.run(_test_outbox_worker_marks_unknown_products_as_permanent_failure())


async def _test_outbox_worker_marks_unknown_products_as_permanent_failure() -> None:
    store = InMemoryOutboxStore(max_attempts=5)

    async def _handler(event: object) -> None:
        raise UnknownProductNamesError(("Неизвестный товар",))

    processors = OutboxProcessorRegistry()
    processors.register(REVISION_TELEGRAM_HANDLER_ID, _handler)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    worker = OutboxWorker(store=store, processors=processors)
    await worker.process_batch()

    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_FAILED
    assert entry["attempts"] == 1
    assert "Неизвестный товар" in str(entry["last_error"])


def test_outbox_worker_marks_invalid_shape_as_permanent_failure() -> None:
    asyncio.run(_test_outbox_worker_marks_invalid_shape_as_permanent_failure())


async def _test_outbox_worker_marks_invalid_shape_as_permanent_failure() -> None:
    store = InMemoryOutboxStore()
    processors = OutboxProcessorRegistry()
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )
    claimed = store.claim_pending(limit=1)
    malformed_entry = dict(claimed[0])
    malformed_entry["event_document"] = None

    worker = OutboxWorker(store=store, processors=processors)
    await worker._process_entry(malformed_entry)

    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_FAILED
    assert entry["attempts"] == 1
    assert "invalid shape" in str(entry["last_error"]).lower()

    await worker.process_batch()
    assert entry["status"] == OUTBOX_STATUS_FAILED
    assert store.claim_pending(limit=10) == []


def test_in_memory_outbox_claim_pending_respects_future_not_before() -> None:
    # edge: not_before в будущем → claim_pending не возвращает запись
    store = InMemoryOutboxStore()
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    store.enqueue(
        event_id="portion:t1:inv1:reconcile",
        handler_id="settlement_portion_reconcile",
        event_document={"event_id": "portion:t1:inv1:reconcile"},
        not_before=future,
    )
    assert store.claim_pending(limit=10) == []


def test_in_memory_outbox_claim_pending_returns_entry_after_not_before() -> None:
    # happy: not_before в прошлом → claim_pending возвращает запись
    store = InMemoryOutboxStore()
    past = datetime.now(tz=UTC) - timedelta(seconds=1)
    store.enqueue(
        event_id="portion:t1:inv1:reconcile",
        handler_id="settlement_portion_reconcile",
        event_document={"event_id": "portion:t1:inv1:reconcile"},
        not_before=past,
    )
    claimed = store.claim_pending(limit=10)
    assert len(claimed) == 1
    assert claimed[0]["event_id"] == "portion:t1:inv1:reconcile"


def test_in_memory_outbox_claim_pending_without_not_before_is_unaffected() -> None:
    # regression: existing call sites (no not_before) — immediate claim, unchanged
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )
    claimed = store.claim_pending(limit=10)
    assert len(claimed) == 1
