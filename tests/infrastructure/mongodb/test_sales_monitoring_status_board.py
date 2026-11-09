from __future__ import annotations

import logging
from datetime import UTC, datetime

import mongomock
import pytest

from src.application.sales_monitoring.status_board_pointer import (
    STATUS_BOARD_POINTER_ID,
    StatusBoardPointer,
)
from src.infrastructure.mongodb.sales_monitoring_status_board import (
    MongoStatusBoardPointerStore,
)


def test_mongo_status_board_pointer_roundtrip() -> None:
    """happy: upsert _id=ops_no_sales."""
    collection = mongomock.MongoClient()["test"]["sales_monitoring_status_board"]
    store = MongoStatusBoardPointerStore.from_collection(collection)
    assert store.load() is None
    pointer = StatusBoardPointer(
        chat_id=1,
        message_id=7,
        posted_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        last_text="board",
    )
    store.save(pointer)
    doc = collection.find_one({"_id": STATUS_BOARD_POINTER_ID})
    assert doc is not None
    assert doc["message_id"] == 7
    assert store.load() == pointer


def test_mongo_status_board_pointer_malformed_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    collection = mongomock.MongoClient()["test"]["sales_monitoring_status_board"]
    collection.insert_one({"_id": STATUS_BOARD_POINTER_ID, "chat_id": "not-int"})
    store = MongoStatusBoardPointerStore.from_collection(collection)

    with caplog.at_level(logging.ERROR):
        assert store.load() is None

    assert "status_board_pointer_invalid" in caplog.text
