from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import DomainEventPublisher
from src.application.machine_pnl import enqueue_machine_period_pnl_jobs
from src.domain.ids import TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.aggregate import SessionCompletionResult

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class FinalizeReconciliationPort(Protocol):
    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> SessionCompletionResult: ...


@beartype
def enqueue_after_finalize_result(
    *,
    result: SessionCompletionResult,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    publisher: DomainEventPublisher,
) -> None:
    period_ids = result.period_ids
    snapshots_by_id: dict[str, ResponsibilityPeriodReconciliation] = {}
    for period_id in period_ids:
        snapshot = reconciliation_repo.get_by_period_id(period_id)
        if snapshot is not None:
            snapshots_by_id[period_id] = snapshot
    enqueue_machine_period_pnl_jobs(
        period_ids=period_ids,
        snapshots_by_id=snapshots_by_id,
        source_session_id=result.session_id.value,
        publisher=publisher,
    )


@beartype
@dataclass(frozen=True, slots=True)
class FinalizeWithMachinePnlEnqueue:
    """Composition post-hook: enqueue machine PnL jobs after successful finalize."""

    inner: FinalizeReconciliationPort
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    publisher: DomainEventPublisher

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> SessionCompletionResult:
        result = self.inner.execute(
            technician_id=technician_id,
        )
        try:
            enqueue_after_finalize_result(
                result=result,
                reconciliation_repo=self.reconciliation_repo,
                publisher=self.publisher,
            )
        except Exception:
            _LOGGER.exception(
                "machine_pnl enqueue after finalize failed session_id=%s",
                result.session_id.value,
            )
            raise
        return result
