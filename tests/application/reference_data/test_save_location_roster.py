from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.reference_data import (
    LocationRosterEntry,
    LocationRosterInvalid,
    LocationRosterPatch,
    LocationRosterStore,
    SaveLocationRoster,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.domain.ids import MachineId, TechnicianId

_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_MACHINE = MachineId("101")
_OTHER = MachineId("102")
_TECH = TechnicianId("001")


def test_memory_roster_get_missing_returns_none() -> None:
    store: LocationRosterStore = InMemoryLocationRosterStore()
    assert store.is_empty() is True
    assert store.get(_MACHINE) is None
    assert store.list_all() == ()


def test_memory_roster_roundtrip_entry() -> None:
    store = InMemoryLocationRosterStore()
    entry = LocationRosterEntry(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({1}),
        updated_at=_NOW,
        updated_by_telegram_user_id=1001,
    )
    store.replace_all((entry,))
    assert store.is_empty() is False
    loaded = store.get(_MACHINE)
    assert loaded is not None
    assert loaded.technician_id == _TECH
    assert loaded.service_weekdays == frozenset({1})


def test_save_writes_entry_and_audit() -> None:
    store = InMemoryLocationRosterStore()
    use_case = SaveLocationRoster(store=store)
    patch = LocationRosterPatch(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({0, 2}),
    )
    use_case.execute(
        (patch,),
        catalog_machine_ids=frozenset({_MACHINE}),
        directory_technician_ids=frozenset({_TECH}),
        actor_telegram_user_id=1001,
        now=_NOW,
    )
    loaded = store.get(_MACHINE)
    assert loaded is not None
    assert loaded.technician_id == _TECH
    assert loaded.service_weekdays == frozenset({0, 2})
    assert loaded.updated_by_telegram_user_id == 1001
    audit = store.list_audit()
    assert len(audit) == 1
    assert audit[0].before is None
    assert audit[0].after.technician_id == _TECH
    assert audit[0].actor_telegram_user_id == 1001


def test_save_rejects_unknown_technician() -> None:
    store = InMemoryLocationRosterStore()
    use_case = SaveLocationRoster(store=store)
    patch = LocationRosterPatch(
        machine_id=_MACHINE,
        technician_id=TechnicianId("999"),
        service_weekdays=frozenset({0}),
    )
    with pytest.raises(LocationRosterInvalid, match="technician"):
        use_case.execute(
            (patch,),
            catalog_machine_ids=frozenset({_MACHINE}),
            directory_technician_ids=frozenset({_TECH}),
            actor_telegram_user_id=1001,
            now=_NOW,
        )
    assert store.is_empty() is True


def test_save_rejects_unknown_machine() -> None:
    store = InMemoryLocationRosterStore()
    use_case = SaveLocationRoster(store=store)
    patch = LocationRosterPatch(
        machine_id=MachineId("404"),
        technician_id=_TECH,
        service_weekdays=frozenset({0}),
    )
    with pytest.raises(LocationRosterInvalid, match="machine"):
        use_case.execute(
            (patch,),
            catalog_machine_ids=frozenset({_MACHINE}),
            directory_technician_ids=frozenset({_TECH}),
            actor_telegram_user_id=1001,
            now=_NOW,
        )
    assert store.is_empty() is True


def test_save_rejects_invalid_weekday() -> None:
    store = InMemoryLocationRosterStore()
    use_case = SaveLocationRoster(store=store)
    patch = LocationRosterPatch(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({7}),
    )
    with pytest.raises(LocationRosterInvalid, match="weekday"):
        use_case.execute(
            (patch,),
            catalog_machine_ids=frozenset({_MACHINE}),
            directory_technician_ids=frozenset({_TECH}),
            actor_telegram_user_id=1001,
            now=_NOW,
        )
    assert store.is_empty() is True


def test_save_batch_is_atomic_on_validation_error() -> None:
    store = InMemoryLocationRosterStore()
    use_case = SaveLocationRoster(store=store)
    good = LocationRosterPatch(
        machine_id=_MACHINE,
        technician_id=_TECH,
        service_weekdays=frozenset({0}),
    )
    bad = LocationRosterPatch(
        machine_id=_OTHER,
        technician_id=TechnicianId("999"),
        service_weekdays=frozenset({1}),
    )
    with pytest.raises(LocationRosterInvalid):
        use_case.execute(
            (good, bad),
            catalog_machine_ids=frozenset({_MACHINE, _OTHER}),
            directory_technician_ids=frozenset({_TECH}),
            actor_telegram_user_id=1001,
            now=_NOW,
        )
    assert store.get(_MACHINE) is None
    assert store.list_audit() == ()
