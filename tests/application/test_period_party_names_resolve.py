from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.inventory_reconciliation.party_names import resolve_frozen_party_names
from src.application.inventory_reconciliation.period_errors import PeriodSnapshotNotReadyError
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


class _FakeLookup:
    def __init__(self, *, location: str | None, technician: str | None) -> None:
        self._location = location
        self._technician = technician

    def location_name(self, machine_id: MachineId) -> str | None:
        return self._location

    def technician_name(self, technician_id: TechnicianId) -> str | None:
        return self._technician


def _existing(**kwargs: object) -> ResponsibilityPeriodReconciliation:
    base = dict(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 8, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="complete",
    )
    base.update(kwargs)
    return ResponsibilityPeriodReconciliation(**base)  # type: ignore[arg-type]


def test_resolve_strips_and_returns_names() -> None:
    loc, tech = resolve_frozen_party_names(
        _FakeLookup(location="  Loc A  ", technician="  Tech  "),
        machine_id=MachineId("vm-01"),
        technician_id=TechnicianId("tech-a"),
        period_id="rev-1:rev-2",
        existing=None,
    )
    assert loc == "Loc A"
    assert tech == "Tech"


def test_resolve_missing_location_raises_not_ready_with_which() -> None:
    with pytest.raises(PeriodSnapshotNotReadyError, match="location_name") as exc:
        resolve_frozen_party_names(
            _FakeLookup(location=None, technician="Tech"),
            machine_id=MachineId("vm-01"),
            technician_id=TechnicianId("tech-a"),
            period_id="rev-1:rev-2",
            existing=None,
        )
    assert "location_name" in str(exc.value)


def test_resolve_missing_technician_raises_not_ready_with_which() -> None:
    with pytest.raises(PeriodSnapshotNotReadyError, match="technician_name"):
        resolve_frozen_party_names(
            _FakeLookup(location="Loc", technician="  "),
            machine_id=MachineId("vm-01"),
            technician_id=TechnicianId("tech-a"),
            period_id="rev-1:rev-2",
            existing=None,
        )


def test_resolve_preserve_if_present_ignores_lookup() -> None:
    loc, tech = resolve_frozen_party_names(
        _FakeLookup(location="NEW", technician="NEW TECH"),
        machine_id=MachineId("vm-01"),
        technician_id=TechnicianId("tech-a"),
        period_id="rev-1:rev-2",
        existing=_existing(location_name="OLD LOC", technician_name="OLD TECH"),
    )
    assert loc == "OLD LOC"
    assert tech == "OLD TECH"


def test_resolve_legacy_empty_existing_requires_lookup() -> None:
    loc, tech = resolve_frozen_party_names(
        _FakeLookup(location="Loc", technician="Tech"),
        machine_id=MachineId("vm-01"),
        technician_id=TechnicianId("tech-a"),
        period_id="rev-1:rev-2",
        existing=_existing(location_name="", technician_name=""),
    )
    assert loc == "Loc"
    assert tech == "Tech"


def test_resolve_partial_existing_requires_lookup() -> None:
    loc, tech = resolve_frozen_party_names(
        _FakeLookup(location="Loc from Sheets", technician="Tech from Sheets"),
        machine_id=MachineId("vm-01"),
        technician_id=TechnicianId("tech-a"),
        period_id="rev-1:rev-2",
        existing=_existing(location_name="OLD LOC", technician_name=""),
    )
    assert loc == "Loc from Sheets"
    assert tech == "Tech from Sheets"


def test_resolve_both_missing_raises_not_ready_with_combined_which() -> None:
    with pytest.raises(PeriodSnapshotNotReadyError, match=r"which=location_name\+technician_name"):
        resolve_frozen_party_names(
            _FakeLookup(location=None, technician=None),
            machine_id=MachineId("vm-01"),
            technician_id=TechnicianId("tech-a"),
            period_id="rev-1:rev-2",
            existing=None,
        )
