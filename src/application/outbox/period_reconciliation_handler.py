from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation import CloseResponsibilityPeriodOnRevision
from src.application.technician_settlement import PostPeriodAccountability
from src.domain.machine_operations.events import RevisionCompleted


@beartype
@dataclass(frozen=True, slots=True)
class PeriodReconciliationHandler:
    close_period: CloseResponsibilityPeriodOnRevision
    post_accountability: PostPeriodAccountability

    @beartype
    async def process(self, event: RevisionCompleted) -> None:
        snapshot = self.close_period.execute(closing_event=event)
        if snapshot is None or snapshot.reconciled or snapshot.ledger_posted:
            return
        if snapshot.status == "complete":
            self.post_accountability.execute(snapshot=snapshot)
