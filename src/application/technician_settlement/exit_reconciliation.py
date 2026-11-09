from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.technician_settlement.apply_draft import (
    maybe_create_residual,
    unpack_draft_plan,
)
from src.application.technician_settlement.draft import (
    ReconciliationDraft,
    serialize_exit_plan,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.finalize_reconciliation import (
    TechnicianWarehouseSessionFinalizePort,
)
from src.application.technician_settlement.list_technician_reconciliation_blockers import (
    ListTechnicianReconciliationBlockersResult,
)
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.application.technician_settlement.preview_reconciliation import ReconciliationPreview
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
    compute_residual,
)
from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)
from src.application.technician_settlement.scope import ledger_balance_for
from src.application.technician_warehouse.ports import (
    ImportedTransferRef,
    TechnicianWarehouseRepository,
)
from src.domain.ids import ReconciliationSessionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.aggregate import (
    CompleteReconciliationSession,
    SessionCompletionResult,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import WarehouseTransferRef
from src.domain.technician_warehouse.models import TechnicianWarehouseDelta

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "FinalizeExitTechnicianReconciliation",
    "PreviewExitTechnicianReconciliation",
]


@runtime_checkable
class ExitReconciliationBlockersPort(Protocol):
    @beartype
    def execute(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> ListTechnicianReconciliationBlockersResult: ...


@beartype
@dataclass(frozen=True, slots=True)
class _ExitPlan:
    scope: tuple[ResponsibilityPeriodReconciliation, ...]
    ledger_balance_session: dict[str, Decimal]
    warehouse_inventory_id: str
    warehouse_inventory_moment: datetime
    warehouse_delta_by_sku: dict[str, Decimal]
    calculated_stock_by_sku: dict[str, Decimal]
    actual_stock_by_sku: dict[str, Decimal]
    previous_actual_by_sku: dict[str, Decimal]
    supply_in_by_sku: dict[str, Decimal]
    returns_by_sku: dict[str, Decimal]
    loadings_by_sku: dict[str, Decimal]
    transfer_refs: tuple[ImportedTransferRef, ...]
    residual_by_sku: dict[str, Decimal]
    executed_at: datetime


@beartype
def _build_exit_plan(
    *,
    technician_id: TechnicianId,
    warehouse_repository: TechnicianWarehouseRepository,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    blockers: ExitReconciliationBlockersPort,
    executed_at: datetime | None = None,
) -> _ExitPlan:
    warehouse = warehouse_repository.get(technician_id)
    if not warehouse.is_closed():
        raise ReconciliationBlocked(
            "warehouse is not closed; use close-technician-warehouse",
        )
    delta = warehouse.latest_warehouse_delta()
    if delta is None:
        raise ReconciliationBlocked("no technician warehouse inventory / exit delta missing")

    blockers_result = blockers.execute(technician_id)
    if blockers_result.pending_sales:
        raise ReconciliationBlocked("pending_sales blocker")
    if blockers_result.operational_open:
        raise ReconciliationBlocked("operational_open blocker")

    unposted = reconciliation_repo.list_complete_unposted(technician_id=technician_id)
    if unposted:
        raise ReconciliationBlocked("complete periods without ledger_posted (unposted)")

    posted = reconciliation_repo.list_posted_unreconciled(technician_id=technician_id)
    if not posted:
        raise ReconciliationBlocked("nothing to reconcile in window")

    scope = tuple(sorted(posted, key=lambda s: s.period_id))
    ledger = ledger_balance_for(scope)
    warehouse_delta_by_sku = dict(delta.delta_by_sku)
    residual = compute_residual(ledger, warehouse_delta_by_sku)
    moment = executed_at if executed_at is not None else datetime.now(tz=UTC)
    return _ExitPlan(
        scope=scope,
        ledger_balance_session=ledger,
        warehouse_inventory_id=delta.current_inventory_id,
        warehouse_inventory_moment=delta.current_inventory_moment,
        warehouse_delta_by_sku=warehouse_delta_by_sku,
        calculated_stock_by_sku=dict(delta.calculated_by_sku),
        actual_stock_by_sku=dict(delta.actual_by_sku),
        previous_actual_by_sku=dict(delta.previous_actual_by_sku),
        supply_in_by_sku=dict(delta.supply_in_by_sku),
        returns_by_sku=dict(delta.returns_by_sku),
        loadings_by_sku=dict(delta.loadings_by_sku),
        transfer_refs=_transfer_refs_from_domain_delta(delta),
        residual_by_sku=residual,
        executed_at=moment,
    )


@beartype
def _transfer_refs_from_domain_delta(
    delta: TechnicianWarehouseDelta,
) -> tuple[ImportedTransferRef, ...]:
    return tuple(
        ImportedTransferRef(document_id, content_hash)
        for document_id, content_hash in zip(
            delta.transfer_document_ids,
            delta.transfer_content_hashes,
            strict=True,
        )
    )


@beartype
@dataclass(frozen=True, slots=True)
class PreviewExitTechnicianReconciliation:
    warehouse_repository: TechnicianWarehouseRepository
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    blockers: ExitReconciliationBlockersPort
    draft_store: ReconciliationDraftStore

    @beartype
    def build_preview(self, *, technician_id: TechnicianId) -> ReconciliationPreview:
        plan = _build_exit_plan(
            technician_id=technician_id,
            warehouse_repository=self.warehouse_repository,
            reconciliation_repo=self.reconciliation_repo,
            blockers=self.blockers,
        )
        preview = ReconciliationPreview(
            technician_id=technician_id,
            anchor_at=plan.executed_at,
            scope=plan.scope,
            deferred=(),
            ledger_balance_session=plan.ledger_balance_session,
            warehouse_inventory_id=plan.warehouse_inventory_id,
            warehouse_inventory_moment=plan.warehouse_inventory_moment,
            warehouse_delta_by_sku=plan.warehouse_delta_by_sku,
            warehouse_source="domain_technician_warehouse",
            calculated_stock_by_sku=plan.calculated_stock_by_sku,
            actual_stock_by_sku=plan.actual_stock_by_sku,
            previous_actual_by_sku=plan.previous_actual_by_sku,
            supply_in_by_sku=plan.supply_in_by_sku,
            returns_by_sku=plan.returns_by_sku,
            loadings_by_sku=plan.loadings_by_sku,
            transfer_refs=plan.transfer_refs,
            unmatched_products=(),
            blockers=(),
            can_finalize=True,
            residual_by_sku=plan.residual_by_sku,
        )
        self.draft_store.upsert(
            ReconciliationDraft(
                technician_id=technician_id.value,
                kind="exit",
                warehouse_inventory_id=plan.warehouse_inventory_id,
                warehouse_inventory_moment=plan.warehouse_inventory_moment,
                plan=serialize_exit_plan(
                    period_ids=tuple(s.period_id for s in plan.scope),
                    warehouse_delta_by_sku=plan.warehouse_delta_by_sku,
                    ledger_balance_before=plan.ledger_balance_session,
                    residual_by_sku=plan.residual_by_sku,
                    calculated_stock_by_sku=plan.calculated_stock_by_sku,
                    actual_stock_by_sku=plan.actual_stock_by_sku,
                    previous_actual_by_sku=plan.previous_actual_by_sku,
                    supply_in_by_sku=plan.supply_in_by_sku,
                    returns_by_sku=plan.returns_by_sku,
                    loadings_by_sku=plan.loadings_by_sku,
                    transfer_refs=tuple(
                        (ref.external_document_id, ref.content_hash) for ref in plan.transfer_refs
                    ),
                ),
                updated_at=datetime.now(tz=UTC),
                anchor_at=None,
            )
        )
        _LOGGER.info(
            "draft upsert kind=exit technician_id=%s inventory_id=%s",
            technician_id.value,
            plan.warehouse_inventory_id,
        )
        return preview

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> ReconciliationPreview:
        return self.build_preview(technician_id=technician_id)


@beartype
def _exit_session_id(
    technician_id: TechnicianId,
    warehouse_inventory_id: str,
) -> ReconciliationSessionId:
    return ReconciliationSessionId(f"{technician_id.value}:exit:{warehouse_inventory_id}")


@beartype
def _warehouse_transfer_refs(
    refs: tuple[ImportedTransferRef, ...],
) -> tuple[WarehouseTransferRef, ...]:
    return tuple(
        WarehouseTransferRef(
            external_document_id=ref.external_document_id,
            content_hash=ref.content_hash,
        )
        for ref in refs
    )


@beartype
@dataclass(frozen=True, slots=True)
class FinalizeExitTechnicianReconciliation:
    warehouse_repository: TechnicianWarehouseRepository
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    settlement_executor: TechnicianSettlementExecutor
    settlement_repository: TechnicianSettlementRepository
    residual_repo: ReconciliationResidualDocumentRepository
    warehouse_finalize: TechnicianWarehouseSessionFinalizePort
    draft_store: ReconciliationDraftStore

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> SessionCompletionResult:
        draft = self.draft_store.get(technician_id.value, "exit")
        if draft is None:
            _LOGGER.warning("draft missing technician_id=%s kind=exit", technician_id.value)
            raise ReconciliationBlocked("no reconciliation draft")

        warehouse = self.warehouse_repository.get(technician_id)
        if not warehouse.is_closed():
            raise ReconciliationBlocked(
                "warehouse is not closed; use close-technician-warehouse",
            )
        delta = warehouse.latest_warehouse_delta()
        if delta is None or delta.current_inventory_id != draft.warehouse_inventory_id:
            _LOGGER.warning(
                "draft stale technician_id=%s draft_inventory_id=%s",
                technician_id.value,
                draft.warehouse_inventory_id,
            )
            raise ReconciliationBlocked("draft stale")

        session_id = _exit_session_id(technician_id, draft.warehouse_inventory_id)
        existing = self.settlement_repository.get(technician_id).completion_result_for(session_id)
        if existing is not None:
            self.warehouse_finalize.finalize_transfers(session_id.value)
            self.draft_store.delete(technician_id.value, "exit")
            return existing

        maps = unpack_draft_plan(draft.plan, include_deferred=False)
        executed_at = datetime.now(tz=UTC)
        command = CompleteReconciliationSession(
            session_id=session_id,
            mode="exit_warehouse_closed",
            anchor_at=executed_at,
            period_ids=maps.period_ids,
            deferred_period_ids=(),
            warehouse_inventory_id=draft.warehouse_inventory_id,
            warehouse_inventory_moment=draft.warehouse_inventory_moment,
            warehouse_delta_by_sku=maps.warehouse_delta_by_sku,
            warehouse_source="domain_technician_warehouse",
            warehouse_transfer_refs=_warehouse_transfer_refs(maps.transfer_refs),
            ledger_balance_before=maps.ledger_balance_before,
            residual_by_sku=maps.residual_by_sku,
            finalized_at=executed_at,
            executed_at=executed_at,
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
        self.warehouse_finalize.finalize_transfers(command.session_id.value)
        self.draft_store.delete(technician_id.value, "exit")
        _LOGGER.info(
            "draft applied technician_id=%s kind=exit session_id=%s",
            technician_id.value,
            command.session_id.value,
        )
        return result
