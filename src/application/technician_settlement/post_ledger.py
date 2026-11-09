from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.domain.ids import TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


@runtime_checkable
class PostPeriodAccountabilityPort(Protocol):
    @beartype
    def execute(self, *, snapshot: ResponsibilityPeriodReconciliation) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class PostLedgerForCompletePeriods:
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    post_accountability: PostPeriodAccountabilityPort

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId | None = None,
        all_periods: bool = False,
    ) -> tuple[str, ...]:
        if technician_id is None and not all_periods:
            return ()
        snapshots = self.reconciliation_repo.list_complete_unposted(technician_id=technician_id)
        posted: list[str] = []
        for snapshot in snapshots:
            self.post_accountability.execute(snapshot=snapshot)
            posted.append(snapshot.period_id)
        return tuple(posted)
