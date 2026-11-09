from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import pytest
from pymongo.database import Database

from src.infrastructure.outbox.mongo import MongoOutboxStore

pytestmark = pytest.mark.integration

_EVENT_ID = "event-claim-fencing"
_HANDLER_ID = "handler-claim-fencing"


def _store(mongo_database: Database) -> MongoOutboxStore:
    return MongoOutboxStore.from_collection(
        mongo_database["outbox"],
        max_attempts=3,
        processing_lease_seconds=10,
    )


def _expire_claim(mongo_database: Database, entry_id: str) -> None:
    mongo_database["outbox"].update_one(
        {"entry_id": entry_id},
        {"$set": {"claimed_at": datetime.now(tz=UTC) - timedelta(seconds=30)}},
    )


def test_stale_claim_cannot_complete_reclaimed_entry(mongo_database: Database) -> None:
    store = _store(mongo_database)
    assert store.enqueue(
        event_id=_EVENT_ID,
        handler_id=_HANDLER_ID,
        event_document={"event_id": _EVENT_ID},
    )
    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    entry_id = str(claimed[0]["entry_id"])
    stale_claim_id = str(claimed[0]["claim_id"])
    _expire_claim(mongo_database, entry_id)

    start = threading.Barrier(2)
    after_reclaim = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def reclaim_owner() -> None:
        start.wait()
        assert store.reclaim_stuck_processing() == 1
        claimed_again = store.claim_pending(limit=1)
        assert len(claimed_again) == 1
        outcomes["current_claim_id"] = str(claimed_again[0]["claim_id"])
        after_reclaim.wait()

    def stale_complete() -> None:
        start.wait()
        after_reclaim.wait()
        outcomes["stale_marked"] = store.mark_processed(entry_id, claim_id=stale_claim_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reclaim_owner), executor.submit(stale_complete)]
        for future in as_completed(futures):
            future.result()

    current_claim_id = str(outcomes["current_claim_id"])
    assert outcomes["stale_marked"] is False
    assert current_claim_id != stale_claim_id
    reloaded = mongo_database["outbox"].find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "processing"
    assert reloaded["claim_id"] == current_claim_id


def test_stale_claim_cannot_mark_reclaimed_entry_failed(mongo_database: Database) -> None:
    store = _store(mongo_database)
    assert store.enqueue(
        event_id=_EVENT_ID,
        handler_id=_HANDLER_ID,
        event_document={"event_id": _EVENT_ID},
    )
    claimed = store.claim_pending(limit=1)
    assert len(claimed) == 1
    entry_id = str(claimed[0]["entry_id"])
    stale_claim_id = str(claimed[0]["claim_id"])
    _expire_claim(mongo_database, entry_id)

    start = threading.Barrier(2)
    after_reclaim = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def reclaim_owner() -> None:
        start.wait()
        assert store.reclaim_stuck_processing() == 1
        claimed_again = store.claim_pending(limit=1)
        assert len(claimed_again) == 1
        outcomes["current_claim_id"] = str(claimed_again[0]["claim_id"])
        after_reclaim.wait()

    def stale_fail() -> None:
        start.wait()
        after_reclaim.wait()
        outcomes["stale_marked"] = store.mark_failed(
            entry_id,
            claim_id=stale_claim_id,
            error_message="stale worker",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reclaim_owner), executor.submit(stale_fail)]
        for future in as_completed(futures):
            future.result()

    current_claim_id = str(outcomes["current_claim_id"])
    assert outcomes["stale_marked"] is False
    reloaded = mongo_database["outbox"].find_one({"entry_id": entry_id})
    assert reloaded is not None
    assert reloaded["status"] == "processing"
    assert reloaded["claim_id"] == current_claim_id
    assert reloaded.get("last_error") != "stale worker"


def test_event_handler_pair_remains_unique_under_concurrent_enqueue(
    mongo_database: Database,
) -> None:
    store = _store(mongo_database)
    barrier = threading.Barrier(2)
    outcomes: list[bool] = []
    lock = threading.Lock()

    def enqueue_once() -> None:
        barrier.wait()
        created = store.enqueue(
            event_id=_EVENT_ID,
            handler_id=_HANDLER_ID,
            event_document={"event_id": _EVENT_ID},
        )
        with lock:
            outcomes.append(created)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(enqueue_once), executor.submit(enqueue_once)]
        for future in as_completed(futures):
            future.result()

    assert sorted(outcomes) == [False, True]
    assert mongo_database["outbox"].count_documents({}) == 1
