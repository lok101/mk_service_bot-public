from __future__ import annotations

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.domain.ids import TechnicianId
from src.domain.inventory_reconciliation.snapshot import (
    ResponsibilityPeriodReconciliation,
)


@beartype
def pending_sales_snapshots_for_technician(
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    technician_id: TechnicianId,
) -> list[ResponsibilityPeriodReconciliation]:
    """Return all pending snapshots for list-blockers/planner input.

    This is not ``scope.blockers``: anchor filtering remains exclusively in
    ``compute_scope``.
    """
    return [
        snapshot
        for snapshot in reconciliation_repo.list_by_status(status="pending_sales")
        if snapshot.responsible_technician_id == technician_id
    ]
