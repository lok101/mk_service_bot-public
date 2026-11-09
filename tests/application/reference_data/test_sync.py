from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.sync import SyncReferenceData

_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_ROW = ["129", "Локация 1", "Иван", "tech-1"]
_SID = ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS
_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


class _MemoryStore:
    def __init__(self) -> None:
        self.snapshots: dict[ReferenceDataSourceId, ReferenceDataSnapshot] = {}
        self.errors: list[tuple[ReferenceDataSourceId, str]] = []

    def get(self, source_id):
        return self.snapshots.get(source_id)

    def put(self, snapshot):
        self.snapshots[snapshot.source_id] = snapshot

    def get_by_id(self, snapshot_id: str):
        return None

    def delete_by_id(self, snapshot_id: str) -> None:
        return None

    def record_sync_error(self, source_id, message, at):
        self.errors.append((source_id, message))
        existing = self.snapshots.get(source_id)
        if existing is not None:
            self.snapshots[source_id] = replace(
                existing,
                last_sync_error=None,  # not asserted here
            )


class _Reader:
    def __init__(self, rows_by_source: dict[ReferenceDataSourceId, list[list[str]]]) -> None:
        self._rows_by_source = rows_by_source
        self.calls = 0

    def read_rows(self, source_id):
        self.calls += 1
        return self._rows_by_source[source_id]


class _FailingReader:
    def read_rows(self, source_id):
        raise RuntimeError("sheets down")


def _sync(reader, store, provider) -> SyncReferenceData:
    return SyncReferenceData(
        reader=reader,
        store=store,
        provider=provider,
        source_ids=(_SID,),
        now=lambda: _NOW,
    )


def test_success_updates_provider_and_store() -> None:
    store = _MemoryStore()
    provider = ReferenceDataProvider()
    _sync(_Reader({_SID: [_HEADER, _ROW]}), store, provider).sync_all()
    assert provider.coffee_locations_or_none() is not None
    assert store.snapshots[_SID].last_sync_error is None
    assert store.snapshots[_SID].last_fetched_at == _NOW


def test_reader_failure_keeps_last_known_good() -> None:
    store = _MemoryStore()
    provider = ReferenceDataProvider()
    provider.apply_rows(_SID, [_HEADER, _ROW])
    _sync(_FailingReader(), store, provider).sync_all()
    assert provider.coffee_locations_or_none() is not None  # kept
    assert store.errors and store.errors[0][0] == _SID


def test_parse_failure_is_atomic() -> None:
    store = _MemoryStore()
    provider = ReferenceDataProvider()
    _sync(_Reader({_SID: [["wrong", "header"]]}), store, provider).sync_all()
    assert provider.coffee_locations_or_none() is None
    assert store.errors and store.errors[0][0] == _SID
    assert _SID not in store.snapshots


def test_parse_failure_keeps_last_known_good_in_provider() -> None:
    store = _MemoryStore()
    provider = ReferenceDataProvider()
    provider.apply_rows(_SID, [_HEADER, _ROW])
    _sync(_Reader({_SID: [["wrong", "header"]]}), store, provider).sync_all()
    assert provider.coffee_locations_or_none() is not None
    assert store.errors and store.errors[0][0] == _SID


def test_no_op_preserves_content_updated_at_but_bumps_fetched_at() -> None:
    store = _MemoryStore()
    provider = ReferenceDataProvider()
    reader = _Reader({_SID: [_HEADER, _ROW]})
    sync = SyncReferenceData(
        reader=reader,
        store=store,
        provider=provider,
        source_ids=(_SID,),
        now=lambda: _NOW,
    )
    sync.sync_all()
    first_updated_at = store.snapshots[_SID].content_updated_at

    later = datetime(2026, 7, 1, 13, 0, 0, tzinfo=UTC)
    SyncReferenceData(
        reader=reader,
        store=store,
        provider=provider,
        source_ids=(_SID,),
        now=lambda: later,
    ).sync_all()

    snapshot = store.snapshots[_SID]
    assert snapshot.content_updated_at == first_updated_at
    assert snapshot.last_fetched_at == later
