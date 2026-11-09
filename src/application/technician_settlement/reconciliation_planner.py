from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.shared.async_bridge import run_coroutine_sync
from src.application.technician_settlement.pending_sales import (
    pending_sales_snapshots_for_technician,
)
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.application.technician_settlement.scope import (
    ReconciliationScope,
    compute_scope,
)
from src.application.technician_warehouse import (
    FinalizedTransferChangedError,
    MoySkladUnavailable,
    TechnicianWarehouseImportBlocked,
    TechnicianWarehouseImportResult,
)
from src.application.technician_warehouse.ports import (
    ImportedTransferRef,
    TechnicianWarehouseDelta,
    TechnicianWarehouseDeltaPort,
    TechnicianWarehouseRepository,
    UnmatchedMsProduct,
)
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse.models import (
    TechnicianWarehouseDelta as DomainWarehouseDelta,
)

_NO_WAREHOUSE_INVENTORY_BLOCKER = "no technician warehouse inventory in window"
_FINALIZED_TRANSFER_CHANGED_BLOCKER = "finalized MS transfer changed"
_EMPTY_SCOPE_BLOCKER = "nothing to reconcile in window"


class ReconciliationBlocked(Exception):
    """Preview/finalize cannot proceed; carries an operator-facing reason."""


class EmptyReconcileScope(ReconciliationBlocked):
    """Empty reconcile window; carries warehouse delta/residual for auto-path persist."""

    @beartype
    def __init__(
        self,
        *,
        warehouse_delta_by_sku: dict[str, Decimal],
        residual_by_sku: dict[str, Decimal],
        warehouse_inventory_id: str,
        warehouse_inventory_moment: datetime,
    ) -> None:
        super().__init__(_EMPTY_SCOPE_BLOCKER)
        self.warehouse_delta_by_sku = dict(warehouse_delta_by_sku)
        self.residual_by_sku = dict(residual_by_sku)
        self.warehouse_inventory_id = warehouse_inventory_id
        self.warehouse_inventory_moment = warehouse_inventory_moment


@beartype
def _transfer_refs_from_domain_delta(
    domain_delta: DomainWarehouseDelta,
) -> tuple[ImportedTransferRef, ...]:
    return tuple(
        ImportedTransferRef(doc_id, content_hash)
        for doc_id, content_hash in zip(
            domain_delta.transfer_document_ids,
            domain_delta.transfer_content_hashes,
            strict=True,
        )
    )


@runtime_checkable
class _WarehouseTransfersImporter(Protocol):
    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult: ...


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationSessionPlan:
    anchor_at: datetime
    scope: ReconciliationScope
    warehouse_inventory_id: str | None
    warehouse_inventory_moment: datetime | None
    warehouse_delta_by_sku: dict[str, Decimal]
    calculated_stock_by_sku: dict[str, Decimal]
    actual_stock_by_sku: dict[str, Decimal]
    previous_actual_by_sku: dict[str, Decimal]
    supply_in_by_sku: dict[str, Decimal]
    returns_by_sku: dict[str, Decimal]
    loadings_by_sku: dict[str, Decimal]
    transfer_refs: tuple[ImportedTransferRef, ...]
    unmatched_products: tuple[UnmatchedMsProduct, ...]
    blockers: tuple[str, ...]
    can_finalize: bool
    residual_by_sku: dict[str, Decimal]


@beartype
def compute_residual(
    ledger: dict[str, Decimal],
    warehouse_delta_by_sku: dict[str, Decimal],
) -> dict[str, Decimal]:
    skus = set(ledger) | set(warehouse_delta_by_sku)
    result: dict[str, Decimal] = {}
    for sku in skus:
        value = ledger.get(sku, Decimal("0")) + warehouse_delta_by_sku.get(sku, Decimal("0"))
        if value != Decimal("0"):
            result[sku] = value
    return result


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationSessionPlanner:
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    settlement_repository: TechnicianSettlementRepository
    warehouse_delta_port: TechnicianWarehouseDeltaPort
    warehouse_repository: TechnicianWarehouseRepository
    importer: _WarehouseTransfersImporter

    @beartype
    def plan(self, technician_id: TechnicianId) -> ReconciliationSessionPlan:
        technician_warehouse = self.warehouse_repository.get(technician_id)
        if technician_warehouse.is_closed():
            raise ReconciliationBlocked("warehouse is closed; use exit-reconcile")

        session_delta = technician_warehouse.compute_warehouse_delta_between_latest_inventories()
        if session_delta is None:
            raise ReconciliationBlocked(_NO_WAREHOUSE_INVENTORY_BLOCKER)
        session_cutoff = session_delta.current_inventory_moment

        import_result: TechnicianWarehouseImportResult | None = None
        import_blockers: list[str] = []
        try:
            import_result = run_coroutine_sync(
                self.importer.execute(technician_id, anchor_at=session_cutoff),
            )
        except MoySkladUnavailable as exc:
            import_blockers.append(str(exc))
        except TechnicianWarehouseImportBlocked as exc:
            import_blockers.append(str(exc))
        except FinalizedTransferChangedError:
            import_blockers.append(_FINALIZED_TRANSFER_CHANGED_BLOCKER)

        scope = self._compute_scope(technician_id=technician_id, anchor_at=session_cutoff)
        aggregate = self.settlement_repository.get(technician_id)
        previous_finalized_at = aggregate.last_session_finalized_at()

        if import_blockers:
            warehouse = None
            blockers = tuple(import_blockers)
        else:
            warehouse, blockers = self._fetch_warehouse_delta(
                technician_id=technician_id,
                after=previous_finalized_at,
                until=session_cutoff,
                skip_import=True,
            )

        warehouse_delta_by_sku = (
            dict(warehouse.warehouse_delta_by_sku) if warehouse is not None else {}
        )
        residual = compute_residual(scope.ledger_balance_session, warehouse_delta_by_sku)
        can_finalize = not blockers

        if import_result is not None:
            transfer_refs = import_result.transfer_refs
            unmatched = import_result.unmatched_products
        elif warehouse is not None:
            transfer_refs = warehouse.transfer_refs
            unmatched = warehouse.unmatched_products
        else:
            transfer_refs = ()
            unmatched = ()

        return ReconciliationSessionPlan(
            anchor_at=session_cutoff,
            scope=scope,
            warehouse_inventory_id=session_delta.current_inventory_id,
            warehouse_inventory_moment=session_delta.current_inventory_moment,
            warehouse_delta_by_sku=warehouse_delta_by_sku,
            calculated_stock_by_sku=(
                dict(warehouse.calculated_stock_by_sku) if warehouse is not None else {}
            ),
            actual_stock_by_sku=(
                dict(warehouse.actual_stock_by_sku) if warehouse is not None else {}
            ),
            previous_actual_by_sku=(
                dict(warehouse.previous_actual_by_sku) if warehouse is not None else {}
            ),
            supply_in_by_sku=dict(warehouse.supply_in_by_sku) if warehouse is not None else {},
            returns_by_sku=dict(warehouse.returns_by_sku) if warehouse is not None else {},
            loadings_by_sku=dict(warehouse.loadings_by_sku) if warehouse is not None else {},
            transfer_refs=transfer_refs,
            unmatched_products=unmatched,
            blockers=blockers,
            can_finalize=can_finalize,
            residual_by_sku=residual,
        )

    @beartype
    def _compute_scope(
        self,
        *,
        technician_id: TechnicianId,
        anchor_at: datetime,
    ) -> ReconciliationScope:
        posted = self.reconciliation_repo.list_posted_unreconciled(technician_id=technician_id)
        pending = pending_sales_snapshots_for_technician(
            self.reconciliation_repo,
            technician_id,
        )
        scope = compute_scope(
            posted_unreconciled=posted,
            pending_in_window=pending,
            anchor_at=anchor_at,
        )
        if scope.blockers:
            raise ReconciliationBlocked("pending periods inside reconciliation window")
        if not scope.scope:
            raise ReconciliationBlocked(_EMPTY_SCOPE_BLOCKER)
        return scope

    @beartype
    def plan_for_inventory(
        self,
        technician_id: TechnicianId,
        *,
        warehouse_inventory_id: str,
        skip_import: bool = False,
    ) -> ReconciliationSessionPlan:
        """Plan a session for an explicit warehouse inventory id (payload SoT).

        When ``skip_import`` is False, MS import runs and warehouse/delta maps are
        reloaded from the repository after a successful import (not the pre-import
        snapshot). When True, delta is taken from the aggregate without import.
        """
        technician_warehouse = self.warehouse_repository.get(technician_id)
        if technician_warehouse.is_closed():
            raise ReconciliationBlocked("warehouse is closed; use exit-reconcile")

        session_delta = technician_warehouse.compute_warehouse_delta_for_inventory_id(
            warehouse_inventory_id,
        )
        if session_delta is None:
            raise ReconciliationBlocked(_NO_WAREHOUSE_INVENTORY_BLOCKER)
        session_cutoff = session_delta.current_inventory_moment

        import_result: TechnicianWarehouseImportResult | None = None
        import_blockers: list[str] = []
        if not skip_import:
            try:
                import_result = run_coroutine_sync(
                    self.importer.execute(technician_id, anchor_at=session_cutoff),
                )
            except MoySkladUnavailable as exc:
                import_blockers.append(str(exc))
            except TechnicianWarehouseImportBlocked as exc:
                import_blockers.append(str(exc))
            except FinalizedTransferChangedError:
                import_blockers.append(_FINALIZED_TRANSFER_CHANGED_BLOCKER)

            if not import_blockers:
                technician_warehouse = self.warehouse_repository.get(technician_id)
                session_delta = technician_warehouse.compute_warehouse_delta_for_inventory_id(
                    warehouse_inventory_id,
                )
                if session_delta is None:
                    raise ReconciliationBlocked(_NO_WAREHOUSE_INVENTORY_BLOCKER)

        try:
            scope = self._compute_scope(technician_id=technician_id, anchor_at=session_cutoff)
        except ReconciliationBlocked as exc:
            if str(exc) != _EMPTY_SCOPE_BLOCKER:
                raise
            warehouse_delta_by_sku = {} if import_blockers else dict(session_delta.delta_by_sku)
            raise EmptyReconcileScope(
                warehouse_delta_by_sku=warehouse_delta_by_sku,
                residual_by_sku=compute_residual({}, warehouse_delta_by_sku),
                warehouse_inventory_id=session_delta.current_inventory_id,
                warehouse_inventory_moment=session_delta.current_inventory_moment,
            ) from exc

        if import_blockers:
            blockers = tuple(import_blockers)
            warehouse_delta_by_sku = {}
            calculated_stock_by_sku: dict[str, Decimal] = {}
            actual_stock_by_sku: dict[str, Decimal] = {}
            previous_actual_by_sku: dict[str, Decimal] = {}
            supply_in_by_sku: dict[str, Decimal] = {}
            returns_by_sku: dict[str, Decimal] = {}
            loadings_by_sku: dict[str, Decimal] = {}
            transfer_refs: tuple[ImportedTransferRef, ...] = ()
            unmatched: tuple[UnmatchedMsProduct, ...] = ()
        else:
            blockers = ()
            warehouse_delta_by_sku = dict(session_delta.delta_by_sku)
            calculated_stock_by_sku = dict(session_delta.calculated_by_sku)
            actual_stock_by_sku = dict(session_delta.actual_by_sku)
            previous_actual_by_sku = dict(session_delta.previous_actual_by_sku)
            supply_in_by_sku = dict(session_delta.supply_in_by_sku)
            returns_by_sku = dict(session_delta.returns_by_sku)
            loadings_by_sku = dict(session_delta.loadings_by_sku)
            if import_result is not None:
                transfer_refs = import_result.transfer_refs
                unmatched = import_result.unmatched_products
            else:
                transfer_refs = _transfer_refs_from_domain_delta(session_delta)
                unmatched = ()

        residual = compute_residual(scope.ledger_balance_session, warehouse_delta_by_sku)
        return ReconciliationSessionPlan(
            anchor_at=session_cutoff,
            scope=scope,
            warehouse_inventory_id=session_delta.current_inventory_id,
            warehouse_inventory_moment=session_delta.current_inventory_moment,
            warehouse_delta_by_sku=warehouse_delta_by_sku,
            calculated_stock_by_sku=calculated_stock_by_sku,
            actual_stock_by_sku=actual_stock_by_sku,
            previous_actual_by_sku=previous_actual_by_sku,
            supply_in_by_sku=supply_in_by_sku,
            returns_by_sku=returns_by_sku,
            loadings_by_sku=loadings_by_sku,
            transfer_refs=transfer_refs,
            unmatched_products=unmatched,
            blockers=blockers,
            can_finalize=not blockers,
            residual_by_sku=residual,
        )

    @beartype
    def _fetch_warehouse_delta(
        self,
        *,
        technician_id: TechnicianId,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> tuple[TechnicianWarehouseDelta | None, tuple[str, ...]]:
        blockers: list[str] = []
        try:
            warehouse = run_coroutine_sync(
                self.warehouse_delta_port.get_delta(
                    technician_id,
                    after=after,
                    until=until,
                    skip_import=skip_import,
                ),
            )
        except MoySkladUnavailable as exc:
            blockers.append(str(exc))
            return None, tuple(blockers)
        except TechnicianWarehouseImportBlocked as exc:
            blockers.append(str(exc))
            return None, tuple(blockers)
        except FinalizedTransferChangedError:
            blockers.append(_FINALIZED_TRANSFER_CHANGED_BLOCKER)
            return None, tuple(blockers)
        if warehouse is None:
            blockers.append(_NO_WAREHOUSE_INVENTORY_BLOCKER)
            return None, tuple(blockers)
        return warehouse, tuple(blockers)
