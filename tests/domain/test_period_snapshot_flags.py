from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


def _snapshot(**overrides: object) -> ResponsibilityPeriodReconciliation:
    base = dict(
        period_id="p1",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="complete",
    )
    base.update(overrides)
    return ResponsibilityPeriodReconciliation(**base)  # type: ignore[arg-type]


def test_flags_default_to_false() -> None:
    snapshot = _snapshot()
    assert snapshot.ledger_posted is False
    assert snapshot.reconciled is False


def test_flags_can_be_set() -> None:
    snapshot = _snapshot(ledger_posted=True, reconciled=True)
    assert snapshot.ledger_posted is True
    assert snapshot.reconciled is True


def test_party_name_fields_default_to_empty_string() -> None:
    snapshot = _snapshot()
    assert snapshot.location_name == ""
    assert snapshot.technician_name == ""


def test_party_name_fields_can_be_set() -> None:
    snapshot = _snapshot(location_name="Локация А", technician_name="Иванов")
    assert snapshot.location_name == "Локация А"
    assert snapshot.technician_name == "Иванов"
