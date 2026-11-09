from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.application.inventory_reconciliation.refresh_targets import (
    compute_machines_to_refresh,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.settlement_fakes import InMemoryPeriodReconciliationRepository


def _snapshot(
    machine_id: str,
    closed_at: datetime,
    *,
    status: str = "pending_sales",
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=f"rev-a:{machine_id}",
        machine_id=MachineId(machine_id),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-a"),
        closing_revision_id=RevisionId("rev-b"),
        opened_at=closed_at - timedelta(days=1),
        closed_at=closed_at,
        lines=(),
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
    )


def test_compute_machines_to_refresh_dedupes_affected_and_pending_due() -> None:
    # happy: affected (с дублем) + pending-due по cursor — оба включены, без дублей
    repo = InMemoryPeriodReconciliationRepository()
    closed = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    repo.save(_snapshot("vm-pending", closed))

    result = compute_machines_to_refresh(
        affected_machine_ids=(MachineId("vm-affected"), MachineId("vm-affected")),
        reconciliation_repo=repo,
        cursor=datetime(2026, 8, 1, 11, 0, tzinfo=UTC),
        tolerance_seconds=0,
    )

    assert result == (MachineId("vm-affected"), MachineId("vm-pending"))


def test_compute_machines_to_refresh_skips_pending_lookup_when_cursor_none() -> None:
    # edge: нет курсора → только affected, pending-due не проверяется
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_snapshot("vm-pending", datetime(2026, 8, 1, 10, 0, tzinfo=UTC)))

    result = compute_machines_to_refresh(
        affected_machine_ids=(),
        reconciliation_repo=repo,
        cursor=None,
        tolerance_seconds=0,
    )

    assert result == ()


def test_compute_machines_to_refresh_skips_reconciled_and_ledger_posted() -> None:
    # error/edge: финализированные снапшоты не переигрываются
    repo = InMemoryPeriodReconciliationRepository()
    closed = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    repo.save(replace(_snapshot("vm-reconciled", closed), reconciled=True))
    repo.save(replace(_snapshot("vm-posted", closed), ledger_posted=True))

    result = compute_machines_to_refresh(
        affected_machine_ids=(),
        reconciliation_repo=repo,
        cursor=datetime(2026, 8, 1, 11, 0, tzinfo=UTC),
        tolerance_seconds=0,
    )

    assert result == ()


def test_compute_machines_to_refresh_respects_tolerance_threshold() -> None:
    # edge: closed_at - tolerance должен быть <= cursor, иначе не pending-due
    repo = InMemoryPeriodReconciliationRepository()
    closed = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    repo.save(_snapshot("vm-pending", closed))

    result = compute_machines_to_refresh(
        affected_machine_ids=(),
        reconciliation_repo=repo,
        cursor=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),  # раньше closed_at - никакого tolerance
        tolerance_seconds=0,
    )

    assert result == ()
