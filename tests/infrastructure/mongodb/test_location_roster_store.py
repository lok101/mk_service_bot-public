from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.reference_data.location_roster import LocationRosterEntry
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.location_roster import MongoLocationRosterStore

_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_MACHINE = MachineId("101")
_TECH = TechnicianId("001")


def test_mongo_roster_roundtrip() -> None:
    client = mongomock.MongoClient()
    store = MongoLocationRosterStore(
        roster_collection=client.db.location_roster,
        audit_collection=client.db.location_roster_audit,
    )
    entry = LocationRosterEntry(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({1, 3}),
        updated_at=_NOW,
        updated_by_telegram_user_id=1001,
    )
    store.save_batch((entry,), actor_telegram_user_id=1001, at=_NOW)
    loaded = store.get(_MACHINE)
    assert loaded is not None
    assert loaded.technician_id == _TECH
    assert loaded.service_weekdays == frozenset({1, 3})
    store.save_batch(
        (
            LocationRosterEntry(
                machine_id=_MACHINE,
                technician_id=None,
                service_weekdays=frozenset(),
                updated_at=_NOW,
                updated_by_telegram_user_id=1002,
            ),
        ),
        actor_telegram_user_id=1002,
        at=_NOW,
    )
    assert store.get(_MACHINE) is not None
    assert store.get(_MACHINE).technician_id is None


def test_mongo_audit_append() -> None:
    client = mongomock.MongoClient()
    store = MongoLocationRosterStore(
        roster_collection=client.db.location_roster,
        audit_collection=client.db.location_roster_audit,
    )
    first = LocationRosterEntry(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({0}),
        updated_at=_NOW,
        updated_by_telegram_user_id=1,
    )
    store.save_batch((first,), actor_telegram_user_id=1, at=_NOW)
    store.save_batch(
        (
            LocationRosterEntry(
                machine_id=_MACHINE,
                technician_id=None,
                service_weekdays=frozenset({2}),
                updated_at=_NOW,
                updated_by_telegram_user_id=2,
            ),
        ),
        actor_telegram_user_id=2,
        at=_NOW,
    )
    audit = store.list_audit()
    assert len(audit) == 2
    assert audit[0].before is None
    assert audit[1].before is not None
    assert audit[1].before.technician_id == _TECH
