from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest

from src.application.reference_data import LocationRosterConflict, LocationRosterEntry
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.location_roster_draft import MongoLocationRosterDraftStore

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)
_MACHINE = MachineId("101")
_TECH = TechnicianId("001")


def _entry(*, at: datetime = _NOW) -> LocationRosterEntry:
    return LocationRosterEntry(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({1}),
        updated_at=at,
        updated_by_telegram_user_id=1001,
    )


def test_mongo_draft_upsert_roundtrip() -> None:
    client = mongomock.MongoClient()
    store = MongoLocationRosterDraftStore(
        draft_collection=client.db.location_roster_draft,
    )
    written = store.upsert(_entry(), expected_updated_at=None)
    loaded = store.get(_MACHINE)
    assert loaded is not None
    assert loaded == written
    assert loaded.technician_id == _TECH
    assert loaded.service_weekdays == frozenset({1})


def test_mongo_draft_upsert_returns_storage_canonical_updated_at() -> None:
    """happy: returned token matches BSON ms precision (autosave → Reset)."""
    client = mongomock.MongoClient()
    store = MongoLocationRosterDraftStore(
        draft_collection=client.db.location_roster_draft,
    )
    with_us = datetime(2026, 8, 26, 12, 0, 0, 123456, tzinfo=UTC)
    written = store.upsert(_entry(at=with_us), expected_updated_at=None)
    assert written.updated_at.microsecond == 123000
    loaded = store.get(_MACHINE)
    assert loaded is not None
    assert loaded.updated_at == written.updated_at


def test_mongo_draft_upsert_stale_raises() -> None:
    client = mongomock.MongoClient()
    store = MongoLocationRosterDraftStore(
        draft_collection=client.db.location_roster_draft,
    )
    store.upsert(_entry(at=_NOW), expected_updated_at=None)
    with pytest.raises(LocationRosterConflict):
        store.upsert(_entry(at=_LATER), expected_updated_at=_LATER)


def test_mongo_draft_replace_all_drops_ids_not_in_new_set() -> None:
    client = mongomock.MongoClient()
    store = MongoLocationRosterDraftStore(
        draft_collection=client.db.location_roster_draft,
    )
    extra = LocationRosterEntry(
        machine_id=MachineId("202"),
        technician_id=_TECH,
        service_weekdays=frozenset({2}),
        updated_at=_NOW,
        updated_by_telegram_user_id=1001,
    )
    store.upsert(_entry(), expected_updated_at=None)
    store.upsert(extra, expected_updated_at=None)
    store.replace_all((_entry(at=_LATER),))
    assert store.get(_MACHINE) is not None
    assert store.get(MachineId("202")) is None


def test_mongo_draft_upsert_conflict_when_expected_none_and_exists() -> None:
    client = mongomock.MongoClient()
    store = MongoLocationRosterDraftStore(
        draft_collection=client.db.location_roster_draft,
    )
    store.upsert(_entry(), expected_updated_at=None)
    with pytest.raises(LocationRosterConflict):
        store.upsert(_entry(at=_LATER), expected_updated_at=None)
