from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.technician_settlement.draft import (
    ReconciliationDraft,
    serialize_inventory_plan,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
    ReconciliationSessionPlan,
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse.ports import ImportedTransferRef, UnmatchedMsProduct
from src.domain.ids import TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation

WarehouseSource = Literal["domain_technician_warehouse"]

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "PreviewTechnicianReconciliation",
    "ReconciliationBlocked",
    "ReconciliationPreview",
]


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationPreview:
    technician_id: TechnicianId
    anchor_at: datetime
    scope: tuple[ResponsibilityPeriodReconciliation, ...]
    deferred: tuple[ResponsibilityPeriodReconciliation, ...]
    ledger_balance_session: dict[str, Decimal]
    warehouse_inventory_id: str | None
    warehouse_inventory_moment: datetime | None
    warehouse_delta_by_sku: dict[str, Decimal]
    warehouse_source: WarehouseSource
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
@dataclass(frozen=True, slots=True)
class PreviewTechnicianReconciliation:
    planner: ReconciliationSessionPlanner
    draft_store: ReconciliationDraftStore

    @beartype
    def build_preview(
        self,
        *,
        technician_id: TechnicianId,
    ) -> ReconciliationPreview:
        plan = self.planner.plan(technician_id=technician_id)
        return self._preview_from_plan(technician_id=technician_id, plan=plan)

    @beartype
    def build_preview_for_inventory(
        self,
        *,
        technician_id: TechnicianId,
        warehouse_inventory_id: str,
        skip_import: bool = True,
    ) -> ReconciliationPreview:
        plan = self.planner.plan_for_inventory(
            technician_id,
            warehouse_inventory_id=warehouse_inventory_id,
            skip_import=skip_import,
        )
        return self._preview_from_plan(technician_id=technician_id, plan=plan)

    @beartype
    def _preview_from_plan(
        self,
        *,
        technician_id: TechnicianId,
        plan: ReconciliationSessionPlan,
    ) -> ReconciliationPreview:
        scope = plan.scope
        preview = ReconciliationPreview(
            technician_id=technician_id,
            anchor_at=plan.anchor_at,
            scope=scope.scope,
            deferred=scope.deferred,
            ledger_balance_session=scope.ledger_balance_session,
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
            unmatched_products=plan.unmatched_products,
            blockers=plan.blockers,
            can_finalize=plan.can_finalize,
            residual_by_sku=plan.residual_by_sku,
        )
        if preview.can_finalize:
            if preview.warehouse_inventory_id is None or preview.warehouse_inventory_moment is None:
                raise ReconciliationBlocked("no technician warehouse inventory in window")
            self.draft_store.upsert(
                ReconciliationDraft(
                    technician_id=technician_id.value,
                    kind="inventory",
                    warehouse_inventory_id=preview.warehouse_inventory_id,
                    warehouse_inventory_moment=preview.warehouse_inventory_moment,
                    plan=serialize_inventory_plan(
                        period_ids=tuple(s.period_id for s in preview.scope),
                        deferred_period_ids=tuple(s.period_id for s in preview.deferred),
                        warehouse_delta_by_sku=preview.warehouse_delta_by_sku,
                        ledger_balance_before=preview.ledger_balance_session,
                        residual_by_sku=preview.residual_by_sku,
                        calculated_stock_by_sku=preview.calculated_stock_by_sku,
                        actual_stock_by_sku=preview.actual_stock_by_sku,
                        previous_actual_by_sku=preview.previous_actual_by_sku,
                        supply_in_by_sku=preview.supply_in_by_sku,
                        returns_by_sku=preview.returns_by_sku,
                        loadings_by_sku=preview.loadings_by_sku,
                        transfer_refs=tuple(
                            (ref.external_document_id, ref.content_hash)
                            for ref in preview.transfer_refs
                        ),
                    ),
                    updated_at=datetime.now(tz=UTC),
                    anchor_at=preview.anchor_at,
                )
            )
            _LOGGER.info(
                "draft upsert kind=inventory technician_id=%s inventory_id=%s",
                technician_id.value,
                preview.warehouse_inventory_id,
            )
        return preview

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> ReconciliationPreview:
        return self.build_preview(technician_id=technician_id)
