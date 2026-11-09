from __future__ import annotations

from datetime import UTC, datetime, timedelta

import mongomock

from src.application.outbox.handler_ids import REVISION_TELEGRAM_HANDLER_ID
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.outbox.mongo import MongoOutboxStore
from src.infrastructure.outbox.serialization import event_to_outbox_document

_EVENT = RevisionCompleted(
    event_id=EventId("event-mongo-outbox"),
    revision_id=RevisionId("rev-1"),
    technician_id=TechnicianId("tech-a"),
    machine_id=MachineId("vm-01"),
    completed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    occurred_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    source=RevisionSource.GOOGLE_FORM,
    form_id="form-1",
    form_token="token-1",
)


def test_mongo_outbox_enqueue_is_idempotent() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
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


def test_mongo_outbox_reclaims_stuck_processing_entries() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(
        collection,
        max_attempts=3,
        processing_lease_seconds=10,
    )
    document = event_to_outbox_document(_EVENT)
    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )

    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    entry_id = str(claimed[0]["entry_id"])
    assert isinstance(claimed[0]["claim_id"], str)
    collection.update_one(
        {"entry_id": entry_id},
        {
            "$set": {
                "claimed_at": datetime.now(tz=UTC) - timedelta(seconds=30),
            },
        },
    )

    reclaimed = store.reclaim_stuck_processing()
    assert reclaimed == 1

    claimed_again = store.claim_pending(limit=1)
    assert len(claimed_again) == 1
    assert str(claimed_again[0]["entry_id"]) == entry_id
    assert claimed_again[0]["claim_id"] != claimed[0]["claim_id"]


def test_mongo_outbox_mark_failed_requires_processing_state() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
    document = event_to_outbox_document(_EVENT)
    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    entry = collection.find_one({"event_id": _EVENT.event_id.value})
    assert entry is not None

    marked = store.mark_failed(
        str(entry["entry_id"]),
        claim_id="unknown-claim",
        error_message="boom",
    )

    assert marked is False
    reloaded = collection.find_one({"entry_id": entry["entry_id"]})
    assert reloaded is not None
    assert reloaded["status"] == "pending"
    assert reloaded["attempts"] == 0


def test_mongo_outbox_mark_failed_clears_claim_and_sets_retry() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
    document = event_to_outbox_document(_EVENT)
    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    entry_id = str(claimed[0]["entry_id"])
    claim_id = str(claimed[0]["claim_id"])

    terminal = store.mark_failed(entry_id, claim_id=claim_id, error_message="transient")

    assert terminal is False
    reloaded = collection.find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "pending"
    assert reloaded["attempts"] == 1
    assert reloaded["claimed_at"] is None
    assert reloaded["claim_id"] is None
    assert reloaded["last_error"] == "transient"


def test_mongo_outbox_mark_processed_requires_current_claim() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(
        collection,
        max_attempts=3,
        processing_lease_seconds=10,
    )
    document = event_to_outbox_document(_EVENT)
    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    entry_id = str(claimed[0]["entry_id"])
    stale_claim_id = str(claimed[0]["claim_id"])
    collection.update_one(
        {"entry_id": entry_id},
        {
            "$set": {
                "claimed_at": datetime.now(tz=UTC) - timedelta(seconds=30),
            },
        },
    )

    assert store.reclaim_stuck_processing() == 1
    claimed_again = store.claim_pending(limit=1)
    assert len(claimed_again) == 1
    current_claim_id = str(claimed_again[0]["claim_id"])

    assert not store.mark_processed(entry_id, claim_id=stale_claim_id)
    reloaded = collection.find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "processing"
    assert reloaded["claim_id"] == current_claim_id

    assert store.mark_processed(entry_id, claim_id=current_claim_id)
    reloaded = collection.find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "processed"
    assert reloaded["claim_id"] is None


def test_mongo_outbox_mark_failed_requires_current_claim() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(
        collection,
        max_attempts=3,
        processing_lease_seconds=10,
    )
    document = event_to_outbox_document(_EVENT)
    assert store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=document,
    )
    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    entry_id = str(claimed[0]["entry_id"])
    stale_claim_id = str(claimed[0]["claim_id"])
    collection.update_one(
        {"entry_id": entry_id},
        {
            "$set": {
                "claimed_at": datetime.now(tz=UTC) - timedelta(seconds=30),
            },
        },
    )

    assert store.reclaim_stuck_processing() == 1
    claimed_again = store.claim_pending(limit=1)
    assert len(claimed_again) == 1
    current_claim_id = str(claimed_again[0]["claim_id"])

    assert not store.mark_failed(
        entry_id,
        claim_id=stale_claim_id,
        error_message="stale worker",
    )
    reloaded = collection.find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "processing"
    assert reloaded["claim_id"] == current_claim_id

    assert (
        store.mark_failed(
            entry_id,
            claim_id=current_claim_id,
            error_message="transient",
        )
        is False
    )
    reloaded = collection.find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "pending"
    assert reloaded["claim_id"] is None


def test_outbox_deferred_retry_respects_max_attempts_override() -> None:
    collection = mongomock.MongoClient().db.outbox
    store = MongoOutboxStore.from_collection(collection, max_attempts=2)
    store.enqueue(event_id="e1", handler_id="h1", event_document={"event_id": "e1"})
    claimed = store.claim_pending(limit=1)
    entry_id = claimed[0]["entry_id"]
    claim_id = claimed[0]["claim_id"]
    before = datetime.now(tz=UTC)
    assert (
        store.mark_failed(
            entry_id,
            claim_id=claim_id,
            error_message="rent pending",
            retry_delay=timedelta(hours=1),
            max_attempts_override=3,
        )
        is False
    )
    reloaded = collection.find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "pending"
    assert reloaded["attempts"] == 1
    next_retry_at = reloaded["next_retry_at"]
    if next_retry_at.tzinfo is None:
        next_retry_at = next_retry_at.replace(tzinfo=UTC)
    delta = next_retry_at - before
    assert timedelta(minutes=50) <= delta <= timedelta(hours=1, minutes=10)

    for expected_attempts in (2, 3):
        collection.update_one(
            {"entry_id": entry_id},
            {"$set": {"next_retry_at": datetime.now(tz=UTC) - timedelta(seconds=1)}},
        )
        claimed = store.claim_pending(limit=1)
        assert len(claimed) == 1
        terminal = store.mark_failed(
            claimed[0]["entry_id"],
            claim_id=claimed[0]["claim_id"],
            error_message="rent pending",
            retry_delay=timedelta(hours=1),
            max_attempts_override=3,
        )
        reloaded = collection.find_one({"entry_id": entry_id})
        assert reloaded is not None
        assert reloaded["attempts"] == expected_attempts
        if expected_attempts < 3:
            assert terminal is False
            assert reloaded["status"] == "pending"
        else:
            assert terminal is True
            assert reloaded["status"] == "failed"


def test_mongo_outbox_claim_pending_respects_future_not_before() -> None:
    # edge: not_before в будущем → claim_pending не возвращает запись
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    store.enqueue(
        event_id="portion:t1:inv1:reconcile",
        handler_id="settlement_portion_reconcile",
        event_document={"event_id": "portion:t1:inv1:reconcile"},
        not_before=future,
    )
    assert store.claim_pending(limit=10) == []


def test_mongo_outbox_claim_pending_returns_entry_after_not_before() -> None:
    # happy: not_before в прошлом → claim_pending возвращает запись
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
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


def test_mongo_outbox_claim_pending_without_not_before_is_unaffected() -> None:
    # regression: existing call sites (no not_before) — immediate claim, unchanged
    client = mongomock.MongoClient()
    collection = client["test_db"]["outbox"]
    store = MongoOutboxStore.from_collection(collection, max_attempts=3)
    store.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=REVISION_TELEGRAM_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )
    claimed = store.claim_pending(limit=10)
    assert len(claimed) == 1
