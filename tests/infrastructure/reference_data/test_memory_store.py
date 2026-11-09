from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)

_SID = ReferenceDataSourceId.BOT_USERS
_NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _snapshot() -> ReferenceDataSnapshot:
    return ReferenceDataSnapshot(
        source_id=_SID,
        rows=(("id", "имя"),),
        content_hash="sha256:x",
        last_fetched_at=_NOW,
        content_updated_at=_NOW,
    )


def test_put_and_get_roundtrip() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.put(_snapshot())
    loaded = store.get(_SID)
    assert loaded is not None
    assert loaded.content_hash == "sha256:x"


def test_get_missing_returns_none() -> None:
    assert InMemoryReferenceDataSnapshotStore().get(_SID) is None


def test_record_sync_error_preserves_rows() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.put(_snapshot())
    store.record_sync_error(_SID, "boom", _NOW)
    loaded = store.get(_SID)
    assert loaded is not None
    assert loaded.rows == (("id", "имя"),)
    assert loaded.last_sync_error is not None
    assert loaded.last_sync_error.message == "boom"


def test_record_sync_error_without_existing_snapshot_is_hydrate_safe() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.record_sync_error(_SID, "boom", _NOW)
    loaded = store.get(_SID)
    assert loaded is not None
    assert loaded.rows == ()
