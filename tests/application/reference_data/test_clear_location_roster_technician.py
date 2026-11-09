from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data import LocationRosterEntry, clear_location_roster_technician
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.domain.ids import MachineId, TechnicianId

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)
_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_WEEKDAYS = frozenset({1, 4})


def _entry(*, tech: TechnicianId | None = _TECH) -> LocationRosterEntry:
    return LocationRosterEntry(
        machine_id=_MACHINE,
        technician_id=tech,
        service_weekdays=_WEEKDAYS,
        updated_at=_NOW,
        updated_by_telegram_user_id=1,
    )


def test_clear_location_roster_technician_happy() -> None:
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    entry = _entry()
    applied.replace_all((entry,))
    draft.replace_all((entry,))
    clear_location_roster_technician(
        _MACHINE,
        applied=applied,
        draft=draft,
        actor_telegram_user_id=42,
        now=_LATER,
    )
    after_applied = applied.get(_MACHINE)
    after_draft = draft.get(_MACHINE)
    assert after_applied is not None
    assert after_draft is not None
    assert after_applied.technician_id is None
    assert after_draft.technician_id is None
    assert after_applied.service_weekdays == _WEEKDAYS
    assert after_draft.service_weekdays == _WEEKDAYS
    assert after_applied.updated_at == _LATER
    assert after_draft.updated_at == _LATER


def test_clear_location_roster_technician_already_unassigned_noop() -> None:
    applied = InMemoryLocationRosterStore()
    draft = InMemoryLocationRosterDraftStore()
    entry = _entry(tech=None)
    applied.replace_all((entry,))
    draft.replace_all((entry,))
    clear_location_roster_technician(
        _MACHINE,
        applied=applied,
        draft=draft,
        actor_telegram_user_id=42,
        now=_LATER,
    )
    after_applied = applied.get(_MACHINE)
    after_draft = draft.get(_MACHINE)
    assert after_applied is not None
    assert after_draft is not None
    assert after_applied.updated_at == _NOW
    assert after_draft.updated_at == _NOW
    assert after_applied.service_weekdays == _WEEKDAYS
