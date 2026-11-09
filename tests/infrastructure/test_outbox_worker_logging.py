from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.application.outbox.handler_ids import REVISION_TELEGRAM_HANDLER_ID
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.outbox.memory import OUTBOX_STATUS_PENDING, InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker

_EVENT = RevisionCompleted(
    event_id=EventId("event-log-1"),
    revision_id=RevisionId("rev-1"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    completed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    source=RevisionSource.GOOGLE_FORM,
    form_id="form-1",
    form_token="token-1",
)


@dataclass
class _RecordingNotifier:
    calls: list[dict[str, object]] = field(default_factory=list)

    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, object],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "handler_id": handler_id,
                "error_message": error_message,
                "entry_id": entry_id,
                "claim_id": claim_id,
            }
        )


class _LostLeaseOutboxStore(InMemoryOutboxStore):
    def mark_failed(
        self,
        entry_id: str,
        *,
        claim_id: str,
        error_message: str,
        permanent: bool = False,
        retry_delay: timedelta | None = None,
        max_attempts_override: int | None = None,
    ) -> bool:
        return False


async def _failing_handler(event: object) -> None:
    raise RuntimeError("simulated handler failure")


def _build_failing_worker(
    store: InMemoryOutboxStore,
    notifier: _RecordingNotifier,
) -> OutboxWorker:
    processors = OutboxProcessorRegistry()
    processors.register(REVISION_TELEGRAM_HANDLER_ID, _failing_handler)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )
    return OutboxWorker(store=store, processors=processors, failure_notifier=notifier)


def test_worker_logs_include_outbox_extra_keys(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    store = InMemoryOutboxStore(max_attempts=1)
    notifier = _RecordingNotifier()
    asyncio.run(_run_failing_worker(store, notifier))

    error_records = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert error_records
    record = error_records[-1]
    assert record.outbox_entry_id
    assert record.outbox_handler_id == REVISION_TELEGRAM_HANDLER_ID
    assert record.outbox_event_id == _EVENT.event_id.value
    assert record.outbox_claim_id
    assert len(notifier.calls) == 1
    assert notifier.calls[0]["handler_id"] == REVISION_TELEGRAM_HANDLER_ID
    assert notifier.calls[0]["error_message"] == "simulated handler failure"


def test_worker_retryable_non_terminal_logs_warning_without_notifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    store = InMemoryOutboxStore(max_attempts=3)
    notifier = _RecordingNotifier()
    asyncio.run(_run_failing_worker(store, notifier))

    error_records = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert error_records == []
    warning_records = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.getMessage().startswith("Outbox handler ")
    ]
    assert len(warning_records) == 1
    record = warning_records[0]
    assert "failed for entry" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert record.outbox_entry_id
    assert record.outbox_handler_id == REVISION_TELEGRAM_HANDLER_ID
    assert record.outbox_event_id == _EVENT.event_id.value
    assert record.outbox_claim_id
    assert notifier.calls == []
    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PENDING


def test_worker_lost_lease_after_fail_logs_warning_without_notifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    store = _LostLeaseOutboxStore(max_attempts=1)
    notifier = _RecordingNotifier()
    asyncio.run(_run_failing_worker(store, notifier))

    error_records = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert error_records == []
    warning_records = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.getMessage().startswith("Outbox handler ")
    ]
    assert len(warning_records) == 1
    record = warning_records[0]
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert record.outbox_entry_id
    assert notifier.calls == []


async def _run_failing_worker(
    store: InMemoryOutboxStore,
    notifier: _RecordingNotifier,
) -> None:
    worker = _build_failing_worker(store, notifier)
    await worker.process_batch()
