from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.domain.ids import AccountabilityId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement import PeriodAccountabilityRecorded
from src.domain.technician_settlement.aggregate import (
    RecordPeriodAccountability,
    TechnicianSettlement,
)


@beartype
def _delta_by_sku(snapshot: ResponsibilityPeriodReconciliation) -> dict[str, Decimal]:
    return {line.product_code: line.delta for line in snapshot.lines if line.delta != Decimal("0")}


@beartype
def _accountability_id(
    technician_id: TechnicianId,
    period_id: str,
) -> AccountabilityId:
    return AccountabilityId(f"{technician_id.value}:{period_id}")


@beartype
@dataclass(frozen=True, slots=True)
class PostPeriodAccountability:
    settlement_executor: TechnicianSettlementExecutor
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository

    @beartype
    def execute(self, *, snapshot: ResponsibilityPeriodReconciliation) -> None:
        if snapshot.status != "complete":
            return
        if snapshot.ledger_posted or snapshot.reconciled:
            return
        if not snapshot.lines:
            # lines=() = расчёт не выполнен (defer / сбой finalize); не писать нулевую
            # accountability и не ставить ledger_posted.
            return
        technician_id = snapshot.responsible_technician_id
        command = RecordPeriodAccountability(
            accountability_id=_accountability_id(technician_id, snapshot.period_id),
            period_id=snapshot.period_id,
            machine_id=snapshot.machine_id,
            delta_by_sku=_delta_by_sku(snapshot),
            closed_at=snapshot.closed_at,
        )

        def _command(
            aggregate: TechnicianSettlement,
        ) -> PeriodAccountabilityRecorded | None:
            return aggregate.record_period_accountability(command)

        self.settlement_executor.execute(technician_id, _command)
        self.reconciliation_repo.mark_ledger_posted(snapshot.period_id)
