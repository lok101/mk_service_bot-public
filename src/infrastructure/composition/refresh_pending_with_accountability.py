from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation import (
    RefreshPendingPeriodReconciliations,
    RefreshPendingResult,
)
from src.application.technician_settlement import PostPeriodAccountability
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class RefreshPendingWithAccountability:
    refresh: RefreshPendingPeriodReconciliations
    post_accountability: PostPeriodAccountability

    @beartype
    def execute(self, *, machine_id: MachineId | None = None) -> RefreshPendingResult:
        result = self.refresh.execute(machine_id=machine_id)
        for snapshot in result.transitioned_to_complete:
            self.post_accountability.execute(snapshot=snapshot)
        return result
