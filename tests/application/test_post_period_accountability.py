from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)


def _snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("10"),
                actual=Decimal("3"),
                calculated=Decimal("5"),
                delta=Decimal("-2"),
            ),
            ReconciliationLine(
                product_code="zero",
                actual_prev=Decimal("1"),
                actual=Decimal("1"),
                calculated=Decimal("1"),
                delta=Decimal("0"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
    )


def _zero_delta_snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("5"),
                actual=Decimal("5"),
                calculated=Decimal("5"),
                delta=Decimal("0"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
    )


def _build_use_case() -> tuple[
    PostPeriodAccountability,
    InMemoryTechnicianSettlementRepository,
    InMemoryPeriodReconciliationRepository,
]:
    event_store = InMemoryTechnicianSettlementEventStore()
    settlement_repo = InMemoryTechnicianSettlementRepository(event_store=event_store)
    period_repo = InMemoryPeriodReconciliationRepository()
    use_case = PostPeriodAccountability(
        settlement_executor=TechnicianSettlementExecutor(repository=settlement_repo),
        reconciliation_repo=period_repo,
    )
    return use_case, settlement_repo, period_repo


def test_post_records_non_zero_deltas_and_marks_posted() -> None:
    use_case, settlement_repo, period_repo = _build_use_case()
    period_repo.save(_snapshot())

    use_case.execute(snapshot=_snapshot())

    aggregate = settlement_repo.get(TechnicianId("tech-a"))
    assert aggregate.net_balance_by_sku() == {"coffee": Decimal("-2")}
    assert period_repo.ledger_posted_periods == ["rev-1:rev-2"]
    assert aggregate.collect_events() == []


def test_post_is_idempotent() -> None:
    use_case, settlement_repo, period_repo = _build_use_case()
    period_repo.save(_snapshot())
    use_case.execute(snapshot=_snapshot())
    use_case.execute(snapshot=_snapshot())
    aggregate = settlement_repo.get(TechnicianId("tech-a"))
    assert aggregate.net_balance_by_sku() == {"coffee": Decimal("-2")}


def test_post_zero_delta_period_still_marks_ledger_posted() -> None:
    use_case, settlement_repo, period_repo = _build_use_case()
    snapshot = _zero_delta_snapshot()
    period_repo.save(snapshot)
    use_case.execute(snapshot=snapshot)
    assert settlement_repo.get(TechnicianId("tech-a")).net_balance_by_sku() == {}
    assert period_repo.ledger_posted_periods == ["rev-1:rev-2"]
    assert len(settlement_repo.events) == 1


def test_post_skips_when_ledger_already_posted() -> None:
    use_case, settlement_repo, period_repo = _build_use_case()
    snapshot = replace(_snapshot(), ledger_posted=True)
    period_repo.save(snapshot)
    use_case.execute(snapshot=snapshot)
    assert settlement_repo.events == []
    assert period_repo.ledger_posted_periods == []


def test_post_skips_when_complete_with_empty_lines() -> None:
    """Не постить accountability / не ставить ledger_posted при lines=() (сбой finalize)."""
    use_case, settlement_repo, period_repo = _build_use_case()
    snapshot = replace(_snapshot(), lines=())
    period_repo.save(snapshot)
    use_case.execute(snapshot=snapshot)
    assert settlement_repo.events == []
    assert period_repo.ledger_posted_periods == []


class _FlakyPeriodRepo(InMemoryPeriodReconciliationRepository):
    def __init__(self) -> None:
        super().__init__()
        self._failed_once = False

    def mark_ledger_posted(self, period_id: str) -> None:
        if not self._failed_once:
            self._failed_once = True
            raise RuntimeError("mark_ledger_posted failed")
        super().mark_ledger_posted(period_id)


def test_retry_after_mark_ledger_posted_failure_is_safe() -> None:
    event_store = InMemoryTechnicianSettlementEventStore()
    settlement_repo = InMemoryTechnicianSettlementRepository(event_store=event_store)
    period_repo = _FlakyPeriodRepo()
    period_repo.save(_snapshot())
    use_case = PostPeriodAccountability(
        settlement_executor=TechnicianSettlementExecutor(repository=settlement_repo),
        reconciliation_repo=period_repo,
    )
    with pytest.raises(RuntimeError, match="mark_ledger_posted failed"):
        use_case.execute(snapshot=_snapshot())
    assert len(settlement_repo.events) == 1
    use_case.execute(snapshot=_snapshot())
    assert period_repo.ledger_posted_periods == ["rev-1:rev-2"]
    assert len(settlement_repo.events) == 1
