from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data import LocationRosterEntry
from src.application.reference_data.location_roster_draft_compare import (
    roster_draft_is_dirty,
)
from src.domain.ids import MachineId, TechnicianId

_T0 = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 8, 26, 11, 0, tzinfo=UTC)
_M = MachineId("101")
_TECH = TechnicianId("001")


def _e(
    *,
    tech: TechnicianId | None = _TECH,
    days: frozenset[int] = frozenset({1}),
    at: datetime = _T0,
) -> LocationRosterEntry:
    return LocationRosterEntry(
        machine_id=_M,
        technician_id=tech,
        service_weekdays=days,
        updated_at=at,
        updated_by_telegram_user_id=1,
    )


def test_roster_draft_is_dirty_false_when_equal() -> None:
    draft = (_e(at=_T1),)
    applied = (_e(at=_T0),)
    assert roster_draft_is_dirty(draft, applied, frozenset({_M})) is False


def test_roster_draft_is_dirty_ignores_updated_at() -> None:
    # same as equal case — different updated_at must NOT mark dirty
    draft = (_e(at=_T1),)
    applied = (_e(at=_T0),)
    assert roster_draft_is_dirty(draft, applied, frozenset({_M})) is False


def test_roster_draft_is_dirty_true_when_technician_differs() -> None:
    draft = (_e(tech=TechnicianId("002")),)
    applied = (_e(tech=_TECH),)
    assert roster_draft_is_dirty(draft, applied, frozenset({_M})) is True
