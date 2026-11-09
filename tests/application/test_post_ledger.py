from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_settlement.post_ledger import PostLedgerForCompletePeriods
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    RecordingPostAccountability,
)


def _snap(period_id: str) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("r1"),
        closing_revision_id=RevisionId("r2"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("0"),
                delta=Decimal("-2"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=False,
    )


def test_post_ledger_posts_all_complete_unposted() -> None:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1"))
    period_repo.save(_snap("p2"))
    post_accountability = RecordingPostAccountability()
    use_case = PostLedgerForCompletePeriods(
        reconciliation_repo=period_repo,
        post_accountability=post_accountability,
    )
    posted = use_case.execute(all_periods=True)
    assert sorted(posted) == ["p1", "p2"]
    assert sorted(snapshot.period_id for snapshot in post_accountability.snapshots) == [
        "p1",
        "p2",
    ]
