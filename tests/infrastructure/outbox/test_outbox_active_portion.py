from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.outbox.handler_ids import (
    SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
    SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
)
from src.infrastructure.outbox.memory import InMemoryOutboxStore


def test_has_active_portion_when_pending() -> None:
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id="portion:t1:inv1:sync",
        handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        event_document={"event_id": "portion:t1:inv1:sync"},
    )
    assert store.find_active_portion_event_id("t1") == "portion:t1:inv1:sync"


def test_has_active_portion_false_when_processed_or_failed() -> None:
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id="portion:t1:inv1:sync",
        handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        event_document={"event_id": "portion:t1:inv1:sync"},
    )
    claimed = store.claim_pending(limit=1)
    entry = claimed[0]
    assert store.mark_processed(entry["entry_id"], claim_id=str(entry["claim_id"]))
    assert store.find_active_portion_event_id("t1") is None

    store.enqueue(
        event_id="portion:t1:inv2:sales",
        handler_id=SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
        event_document={"event_id": "portion:t1:inv2:sales"},
    )
    claimed_fail = store.claim_pending(limit=1)
    fail_entry = claimed_fail[0]
    assert store.mark_failed(
        fail_entry["entry_id"],
        claim_id=str(fail_entry["claim_id"]),
        error_message="boom",
        permanent=True,
    )
    assert store.find_active_portion_event_id("t1") is None


def test_has_active_portion_prefix_scoped_to_technician() -> None:
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id="portion:t2:inv1:reconcile",
        handler_id=SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
        event_document={"event_id": "portion:t2:inv1:reconcile"},
    )
    assert store.find_active_portion_event_id("t1") is None
    assert store.find_active_portion_event_id("t2") == "portion:t2:inv1:reconcile"


def test_has_active_portion_true_while_reconcile_pending_with_future_not_before() -> None:
    # happy: reconcile pending с not_before в будущем — lock всё равно активен
    store = InMemoryOutboxStore()
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    store.enqueue(
        event_id="portion:t1:inv1:reconcile",
        handler_id=SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
        event_document={"event_id": "portion:t1:inv1:reconcile"},
        not_before=future,
    )
    # claim_pending не возвращает запись (карантин), но lock не снят
    assert store.claim_pending(limit=10) == []
    assert store.find_active_portion_event_id("t1") == "portion:t1:inv1:reconcile"
