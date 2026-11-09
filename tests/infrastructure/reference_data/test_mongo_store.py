from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.infrastructure.reference_data.mongo_store import (
    MongoReferenceDataSnapshotStore,
)

_SID = ReferenceDataSourceId.PRODUCT_VITRINE
_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def _store() -> MongoReferenceDataSnapshotStore:
    collection = mongomock.MongoClient().db.reference_data_snapshots
    return MongoReferenceDataSnapshotStore(_collection=collection)


def _snapshot() -> ReferenceDataSnapshot:
    return ReferenceDataSnapshot(
        source_id=_SID,
        rows=(("id", "имя"), ("1", "Кофе")),
        content_hash="sha256:abc",
        last_fetched_at=_NOW,
        content_updated_at=_NOW,
    )


def test_put_and_get_roundtrip() -> None:
    store = _store()
    store.put(_snapshot())
    loaded = store.get(_SID)
    assert loaded is not None
    assert loaded.source_id is _SID
    assert loaded.rows == (("id", "имя"), ("1", "Кофе"))
    assert loaded.content_hash == "sha256:abc"
    assert loaded.last_fetched_at == _NOW


def test_get_missing_returns_none() -> None:
    assert _store().get(_SID) is None


def test_get_by_id_and_delete_by_id_legacy() -> None:
    store = _store()
    collection = store._collection
    collection.replace_one(
        {"_id": "technician_locations"},
        {
            "_id": "technician_locations",
            "rows": [["id локации", "имя локации"], ["129", "Cafe"]],
            "content_hash": "sha256:x",
            "last_fetched_at": _NOW,
            "content_updated_at": _NOW,
            "last_sync_error": None,
        },
        upsert=True,
    )
    loaded = store.get_by_id("technician_locations")
    assert loaded is not None
    assert loaded.rows[1][0] == "129"
    store.delete_by_id("technician_locations")
    assert store.get_by_id("technician_locations") is None


def test_record_sync_error_preserves_rows() -> None:
    store = _store()
    store.put(_snapshot())
    store.record_sync_error(_SID, "boom", _NOW)
    loaded = store.get(_SID)
    assert loaded is not None
    assert loaded.rows == (("id", "имя"), ("1", "Кофе"))
    assert loaded.last_sync_error is not None
    assert loaded.last_sync_error.message == "boom"
