from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.outbox.handler_ids import TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted
from src.infrastructure.outbox.memory import OUTBOX_STATUS_PENDING
from src.infrastructure.outbox.mongo import MongoOutboxStore
from src.infrastructure.outbox.serialization import event_to_outbox_document

_EVENT = LoadingSubmitted(
    event_id=EventId("event-mongo-admin"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    submitted_at=datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
    form_id="form-1",
    form_token="token-1",
)


def _failed_mongo_store() -> MongoOutboxStore:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=1)
    document = event_to_outbox_document(_EVENT)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    store.mark_failed(
        str(claimed[0]["entry_id"]),
        claim_id=str(claimed[0]["claim_id"]),
        error_message="network error",
        permanent=True,
    )
    return store


def test_mongo_outbox_list_failed_filters_by_handler_id() -> None:
    store = _failed_mongo_store()

    all_failed = store.list_failed(limit=10)
    assert len(all_failed) == 1
    assert all_failed[0].handler_id == TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID

    empty = store.list_failed(handler_id="revision_inventory", limit=10)
    assert empty == ()


def test_mongo_outbox_count_failed_matches_list_length() -> None:
    store = _failed_mongo_store()

    assert store.count_failed() == 1
    assert store.count_failed(handler_id=TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID) == 1
    assert store.count_failed(handler_id="revision_inventory") == 0


def test_mongo_outbox_requeue_failed_resets_document() -> None:
    store = _failed_mongo_store()
    summaries = store.list_failed(limit=1)
    entry_id = summaries[0].entry_id

    assert store.requeue_failed(entry_id) is True
    assert store.get_failed_entry(entry_id) is None

    collection = store._collection
    document = collection.find_one({"entry_id": entry_id})
    assert document is not None
    assert document["status"] == OUTBOX_STATUS_PENDING
    assert document["attempts"] == 0
    assert document["last_error"] is None


def test_mongo_outbox_requeue_failed_returns_false_for_pending() -> None:
    store = _failed_mongo_store()
    summaries = store.list_failed(limit=1)
    assert store.requeue_failed(summaries[0].entry_id) is True
    assert store.requeue_failed(summaries[0].entry_id) is False
