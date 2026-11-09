from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_settlement.scope import compute_scope
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


def _snap(period_id, closed_day, status="complete", ledger_posted=True, delta=Decimal("-2")):
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("r1"),
        closing_revision_id=RevisionId("r2"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, closed_day, tzinfo=UTC),
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("0"),
                delta=delta,
            ),
        ),
        sales_lines=(),
        load_count=0,
        status=status,
        ledger_posted=ledger_posted,
        reconciled=False,
    )


def test_scope_splits_by_anchor() -> None:
    posted = [_snap("p1", 10), _snap("p2", 28)]
    pending = [_snap("pb", 5, status="pending_sales", ledger_posted=False)]
    result = compute_scope(
        posted_unreconciled=posted,
        pending_in_window=pending,
        anchor_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
    assert [s.period_id for s in result.scope] == ["p1"]
    assert [s.period_id for s in result.deferred] == ["p2"]
    assert [s.period_id for s in result.blockers] == ["pb"]
    assert result.ledger_balance_session == {"coffee": Decimal("-2")}


def test_scope_excludes_pending_after_anchor() -> None:
    pending = [_snap("pb", 28, status="pending_sales", ledger_posted=False)]
    result = compute_scope(
        posted_unreconciled=[],
        pending_in_window=pending,
        anchor_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
    assert result.blockers == ()
