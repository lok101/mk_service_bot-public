from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.domain.ids import MachineId

__all__ = ["compute_machines_to_refresh"]


@beartype
def compute_machines_to_refresh(
    *,
    affected_machine_ids: Sequence[MachineId],
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    cursor: datetime | None,
    tolerance_seconds: int,
) -> tuple[MachineId, ...]:
    """Тот же набор аппаратов, что `poll_once` рефрешит после import: affected +
    pending-due (по глобальному курсору за вычетом `tolerance_seconds`), без
    дублей, минус уже финализированные (`ledger_posted` / `reconciled`).
    """
    to_refresh: list[MachineId] = []
    seen: set[MachineId] = set()
    for machine_id in affected_machine_ids:
        if machine_id not in seen:
            to_refresh.append(machine_id)
            seen.add(machine_id)
    if cursor is not None:
        for snapshot in reconciliation_repo.list_by_status(status="pending_sales"):
            if snapshot.ledger_posted or snapshot.reconciled:
                continue
            threshold = snapshot.closed_at - timedelta(seconds=tolerance_seconds)
            if threshold <= cursor and snapshot.machine_id not in seen:
                to_refresh.append(snapshot.machine_id)
                seen.add(snapshot.machine_id)
    return tuple(to_refresh)
