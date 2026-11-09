from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.technician_settlement.apply_draft import (
    maybe_create_residual,
    unpack_draft_plan,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.application.technician_settlement.reconciliation_planner import ReconciliationBlocked
from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)
from src.application.technician_warehouse.ports import TechnicianWarehouseRepository
from src.domain.ids import ReconciliationSessionId, TechnicianId
from src.domain.technician_settlement.aggregate import (
    CompleteReconciliationSession,
    SessionCompletionResult,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import WarehouseTransferRef

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class TechnicianWarehouseSessionFinalizePort(Protocol):
    @beartype
    def finalize_transfers(self, session_id: str) -> None:
        """Finalize warehouse transfers for a reconciliation session.

        Idempotent by ``session_id``: a repeat after successful finalize or
        recovery retry must not emit duplicate domain events.
        """


@beartype
def _session_id(
    technician_id: TechnicianId,
    warehouse_inventory_id: str,
) -> ReconciliationSessionId:
    return ReconciliationSessionId(f"{technician_id.value}:{warehouse_inventory_id}")


@beartype
def _legacy_session_id(
    technician_id: TechnicianId,
    anchor_at: datetime,
) -> ReconciliationSessionId:
    return ReconciliationSessionId(f"{technician_id.value}:{anchor_at.isoformat()}")


@beartype
@dataclass(frozen=True, slots=True)
class FinalizeTechnicianReconciliation:
    draft_store: ReconciliationDraftStore
    warehouse_repository: TechnicianWarehouseRepository
    settlement_executor: TechnicianSettlementExecutor
    settlement_repository: TechnicianSettlementRepository
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    residual_repo: ReconciliationResidualDocumentRepository
    warehouse_finalize: TechnicianWarehouseSessionFinalizePort | None = None

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> SessionCompletionResult:
        draft = self.draft_store.get(technician_id.value, "inventory")
        if draft is None:
            if self.draft_store.get(technician_id.value, "exit") is not None:
                _LOGGER.warning(
                    "draft kind mismatch technician_id=%s expected=inventory",
                    technician_id.value,
                )
                raise ReconciliationBlocked("draft kind mismatch")
            _LOGGER.warning("draft missing technician_id=%s kind=inventory", technician_id.value)
            raise ReconciliationBlocked("no reconciliation draft")
        if draft.anchor_at is None:
            _LOGGER.warning("draft missing technician_id=%s kind=inventory", technician_id.value)
            raise ReconciliationBlocked("no reconciliation draft")

        session_id = _session_id(technician_id, draft.warehouse_inventory_id)
        existing = self.settlement_repository.get(technician_id).completion_result_for(
            session_id,
        )
        if existing is None:
            legacy_id = _legacy_session_id(technician_id, draft.anchor_at)
            existing = self.settlement_repository.get(technician_id).completion_result_for(
                legacy_id,
            )
        if existing is not None:
            if self.warehouse_finalize is not None:
                self.warehouse_finalize.finalize_transfers(existing.session_id.value)
            self.draft_store.delete(technician_id.value, "inventory")
            return existing

        warehouse = self.warehouse_repository.get(technician_id)
        if warehouse.is_closed():
            raise ReconciliationBlocked("warehouse is closed; use exit-reconcile")
        current_inventory_id = warehouse.latest_inventory_id
        if current_inventory_id != draft.warehouse_inventory_id:
            _LOGGER.warning(
                "draft stale technician_id=%s draft_inventory_id=%s current_inventory_id=%s",
                technician_id.value,
                draft.warehouse_inventory_id,
                current_inventory_id,
            )
            raise ReconciliationBlocked("draft stale")

        maps = unpack_draft_plan(draft.plan)
        now = datetime.now(tz=UTC)
        command = CompleteReconciliationSession(
            session_id=session_id,
            mode="inventory_delta",
            anchor_at=draft.anchor_at,
            period_ids=maps.period_ids,
            deferred_period_ids=maps.deferred_period_ids,
            warehouse_inventory_id=draft.warehouse_inventory_id,
            warehouse_inventory_moment=draft.warehouse_inventory_moment,
            warehouse_delta_by_sku=maps.warehouse_delta_by_sku,
            warehouse_source="domain_technician_warehouse",
            warehouse_transfer_refs=tuple(
                WarehouseTransferRef(
                    external_document_id=ref.external_document_id,
                    content_hash=ref.content_hash,
                )
                for ref in maps.transfer_refs
            ),
            ledger_balance_before=maps.ledger_balance_before,
            residual_by_sku=maps.residual_by_sku,
            finalized_at=now,
            executed_at=now,
        )

        def _run(aggregate: TechnicianSettlement) -> SessionCompletionResult:
            return aggregate.complete_reconciliation_session(command)

        result = self.settlement_executor.execute(technician_id, _run)
        self.reconciliation_repo.mark_reconciled(command.period_ids)
        maybe_create_residual(
            residual_repo=self.residual_repo,
            technician_id=technician_id,
            command=command,
        )
        if self.warehouse_finalize is not None:
            self.warehouse_finalize.finalize_transfers(command.session_id.value)
        self.draft_store.delete(technician_id.value, "inventory")
        _LOGGER.info(
            "draft applied technician_id=%s kind=inventory session_id=%s",
            technician_id.value,
            command.session_id.value,
        )
        return result
