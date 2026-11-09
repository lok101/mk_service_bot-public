from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.reference_data import LocationRosterConflict, LocationRosterEntry
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.domain.ids import MachineId, TechnicianId

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


def test_draft_memory_upsert_writes_entry() -> None:
    store = InMemoryLocationRosterDraftStore()
    written = store.upsert(_entry(), expected_updated_at=None)
    assert store.get(_MACHINE) == written
    assert written.technician_id == _TECH


def test_draft_memory_upsert_stale_raises_conflict() -> None:
    store = InMemoryLocationRosterDraftStore()
    store.upsert(_entry(at=_NOW), expected_updated_at=None)
    with pytest.raises(LocationRosterConflict):
        store.upsert(_entry(at=_LATER), expected_updated_at=_LATER)
