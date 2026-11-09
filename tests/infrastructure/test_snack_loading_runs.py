from __future__ import annotations

from decimal import Decimal

import mongomock

from src.application.snack_loading.ports import SnackLoadingRunRecord
from src.infrastructure.mongodb.snack_loading_runs import MongoSnackLoadingRunStore


def test_mongo_snack_loading_run_store_roundtrip() -> None:
    coll = mongomock.MongoClient().db.snack_loading_runs
    store = MongoSnackLoadingRunStore.from_collection(coll)
    record = SnackLoadingRunRecord(
        run_id="run-1",
        machine_code="M1",
        move_id="move-1",
        increments=((("M1", "mat", 3), Decimal("2")),),
        domain_applied=True,
    )
    store.save(record)
    got = store.get("run-1")
    assert got == record


def test_mongo_snack_loading_run_store_get_missing_returns_none() -> None:
    coll = mongomock.MongoClient().db.snack_loading_runs
    store = MongoSnackLoadingRunStore.from_collection(coll)
    assert store.get("missing") is None
