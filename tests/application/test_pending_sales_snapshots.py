from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.technician_settlement.pending_sales import (
    pending_sales_snapshots_for_technician,
)
from src.application.technician_settlement.scope import compute_scope
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.settlement_fakes import InMemoryPeriodReconciliationRepository


def _pending_snapshot(
    *,
    technician_id: TechnicianId,
    closed_at: datetime | None = None,
    period_id: str = "period-1",
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-1"),
        responsible_technician_id=technician_id,
        opening_revision_id=RevisionId(f"open-{period_id}"),
        closing_revision_id=RevisionId(f"close-{period_id}"),
        opened_at=datetime(2026, 7, 1, tzinfo=UTC),
        closed_at=closed_at if closed_at is not None else datetime(2026, 7, 8, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="pending_sales",
    )


def _repository_with_pending_snapshots(
    *snapshots: ResponsibilityPeriodReconciliation,
) -> InMemoryPeriodReconciliationRepository:
    repo = InMemoryPeriodReconciliationRepository()
    for snapshot in snapshots:
        repo.save(snapshot)
    return repo


def test_pending_sales_snapshots_for_technician_returns_only_matching_technician() -> None:
    repo = _repository_with_pending_snapshots(
        _pending_snapshot(technician_id=TechnicianId("tech-1"), period_id="p-1"),
        _pending_snapshot(technician_id=TechnicianId("tech-2"), period_id="p-2"),
    )

    result = pending_sales_snapshots_for_technician(
        repo,
        TechnicianId("tech-1"),
    )

    assert [snapshot.responsible_technician_id for snapshot in result] == [
        TechnicianId("tech-1"),
    ]


def test_pending_sales_after_anchor_is_returned_but_not_scope_blocker() -> None:
    anchor_at = datetime(2026, 7, 13, tzinfo=UTC)
    future_pending = _pending_snapshot(
        technician_id=TechnicianId("tech-1"),
        closed_at=anchor_at + timedelta(days=1),
    )
    repo = _repository_with_pending_snapshots(future_pending)

    pending = pending_sales_snapshots_for_technician(
        repo,
        TechnicianId("tech-1"),
    )
    scope = compute_scope(
        posted_unreconciled=[],
        pending_in_window=pending,
        anchor_at=anchor_at,
    )

    assert pending == [future_pending]
    assert scope.blockers == ()
