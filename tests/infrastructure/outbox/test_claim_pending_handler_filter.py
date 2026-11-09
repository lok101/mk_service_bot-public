from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.outbox.handler_ids import (
    REVISION_TELEGRAM_HANDLER_ID,
    SALES_MONITORING_AUDIT_HANDLER_ID,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.outbox.mongo import MongoOutboxStore
from src.infrastructure.outbox.serialization import event_to_outbox_document

_EVENT = RevisionCompleted(
    event_id=EventId("event-claim-filter-1"),
    revision_id=RevisionId("rev-claim-1"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    completed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    source=RevisionSource.GOOGLE_FORM,
    form_id="form-1",
    form_token="token-1",
)


def test_claim_pending_filters_by_handler_id() -> None:
    store = InMemoryOutboxStore()
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=SALES_MONITORING_AUDIT_HANDLER_ID,
        event_document=document,
    )

    claimed = store.claim_pending(limit=10, handler_id=SALES_MONITORING_AUDIT_HANDLER_ID)

    assert len(claimed) == 1
    assert claimed[0]["handler_id"] == SALES_MONITORING_AUDIT_HANDLER_ID


def test_claim_pending_without_handler_id_unchanged() -> None:
    store = InMemoryOutboxStore()
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=SALES_MONITORING_AUDIT_HANDLER_ID,
        event_document=document,
    )

    claimed = store.claim_pending(limit=10)

    assert {entry["handler_id"] for entry in claimed} == {
        REVISION_TELEGRAM_HANDLER_ID,
        SALES_MONITORING_AUDIT_HANDLER_ID,
    }


def test_claim_pending_filters_by_handler_ids_inclusion() -> None:
    store = InMemoryOutboxStore()
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=SALES_MONITORING_AUDIT_HANDLER_ID,
        event_document=document,
    )

    claimed = store.claim_pending(
        limit=10,
        handler_ids=frozenset({REVISION_TELEGRAM_HANDLER_ID}),
    )

    assert len(claimed) == 1
    assert claimed[0]["handler_id"] == REVISION_TELEGRAM_HANDLER_ID


def test_mongo_claim_pending_filters_by_handler_id() -> None:
    collection = mongomock.MongoClient().db.outbox
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=SALES_MONITORING_AUDIT_HANDLER_ID,
        event_document=document,
    )

    claimed = store.claim_pending(limit=10, handler_id=SALES_MONITORING_AUDIT_HANDLER_ID)

    assert len(claimed) == 1
    assert claimed[0]["handler_id"] == SALES_MONITORING_AUDIT_HANDLER_ID
