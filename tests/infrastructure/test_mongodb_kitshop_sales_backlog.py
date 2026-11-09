from __future__ import annotations

import mongomock

from src.infrastructure.mongodb.kitshop_sales_backlog import MongoKitShopSalesBacklogStore


def test_kitshop_mongo_backlog_upsert_claim_hold() -> None:
    collection = mongomock.MongoClient().db.kitshop_sales_backlog
    store = MongoKitShopSalesBacklogStore(collection=collection)
    assert store.upsert_pending(sale_id=100) is True
    assert store.upsert_pending(sale_id=100) is False
    assert store.get_status(100) == "pending"
    claimed = store.claim_pending(limit=1)
    assert claimed == [100]
    store.mark_hold(sale_id=100, reason="no_machine_code")
    assert store.get_status(100) == "hold"
    assert store.claim_pending(limit=1) == [100]
    store.mark_done(sale_id=100)
    assert store.get_status(100) == "done"


def test_kitshop_mongo_backlog_claim_includes_hold() -> None:
    # happy
    collection = mongomock.MongoClient().db.kitshop_sales_backlog
    store = MongoKitShopSalesBacklogStore(collection=collection)
    store.upsert_pending(sale_id=100)
    store.mark_hold(sale_id=100, reason="no_machine_code")
    assert store.get_status(100) == "hold"
    assert store.claim_pending(limit=1) == [100]


def test_kitshop_mongo_backlog_claim_prefers_pending() -> None:
    collection = mongomock.MongoClient().db.kitshop_sales_backlog
    store = MongoKitShopSalesBacklogStore(collection=collection)
    store.upsert_pending(sale_id=1)
    store.upsert_pending(sale_id=2)
    store.mark_hold(sale_id=1, reason="no_machine_code")
    assert store.claim_pending(limit=1) == [2]
    assert store.get_status(1) == "hold"
    assert store.get_status(2) == "pending"
