from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.outbox.admin import (
    GetFailedOutboxEntryService,
    ListFailedOutboxEntriesQuery,
    ListFailedOutboxEntriesService,
    RequeueFailedOutboxEntryError,
    RequeueFailedOutboxEntryService,
)
from src.application.outbox.handler_ids import REVISION_TELEGRAM_HANDLER_ID
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.outbox.memory import (
    OUTBOX_STATUS_FAILED,
    OUTBOX_STATUS_PENDING,
    InMemoryOutboxStore,
)
from src.infrastructure.outbox.serialization import event_to_outbox_document

_EVENT = RevisionCompleted(
    event_id=EventId("event-admin-1"),
    revision_id=RevisionId("rev-1"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    completed_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
    source=RevisionSource.GOOGLE_FORM,
    form_id="form-1",
    form_token="token-1",
)


def _failed_store() -> InMemoryOutboxStore:
    store = InMemoryOutboxStore(max_attempts=1)
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    entry_id = str(claimed[0]["entry_id"])
    claim_id = str(claimed[0]["claim_id"])
    store.mark_failed(
        entry_id,
        claim_id=claim_id,
        error_message="moysklad timeout",
        permanent=True,
    )
    return store


def test_in_memory_outbox_count_failed_matches_failed_entries() -> None:
    store = _failed_store()

    assert store.count_failed() == 1
    assert store.count_failed(handler_id=REVISION_TELEGRAM_HANDLER_ID) == 1
    assert store.count_failed(handler_id="unknown") == 0


def test_list_failed_outbox_entries_returns_summaries() -> None:
    store = _failed_store()
    service = ListFailedOutboxEntriesService(store=store)

    result = service.execute(
        ListFailedOutboxEntriesQuery(handler_id=REVISION_TELEGRAM_HANDLER_ID, limit=10),
    )

    assert len(result) == 1
    assert result[0].event_id == "event-admin-1"
    assert result[0].handler_id == REVISION_TELEGRAM_HANDLER_ID
    assert result[0].last_error == "moysklad timeout"
    assert result[0].attempts >= 1


def test_requeue_failed_outbox_entry_resets_status() -> None:
    store = _failed_store()
    entry_id = next(
        entry_id
        for entry_id, entry in store._entries.items()
        if entry["status"] == OUTBOX_STATUS_FAILED
    )
    service = RequeueFailedOutboxEntryService(store=store)

    service.execute(entry_id)

    entry = store._entries[entry_id]
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 0
    assert entry["last_error"] is None


def test_get_failed_outbox_entry_returns_summary() -> None:
    store = _failed_store()
    entry_id = next(
        entry_id
        for entry_id, entry in store._entries.items()
        if entry["status"] == OUTBOX_STATUS_FAILED
    )
    service = GetFailedOutboxEntryService(store=store)

    summary = service.execute(entry_id)

    assert summary is not None
    assert summary.entry_id == entry_id
    assert summary.event_id == "event-admin-1"


def test_get_failed_outbox_entry_returns_none_for_missing() -> None:
    store = InMemoryOutboxStore()
    service = GetFailedOutboxEntryService(store=store)

    assert service.execute("missing-entry-id") is None


def test_requeue_failed_outbox_entry_raises_when_not_failed() -> None:
    store = InMemoryOutboxStore()
    service = RequeueFailedOutboxEntryService(store=store)

    with pytest.raises(RequeueFailedOutboxEntryError, match="not found or not in failed status"):
        service.execute("missing-entry-id")
