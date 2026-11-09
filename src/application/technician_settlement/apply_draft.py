from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from beartype import beartype

from src.application.technician_settlement.draft import (
    plan_money_map,
    plan_str_tuple,
    plan_transfer_refs,
)
from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)
from src.application.technician_warehouse.ports import ImportedTransferRef
from src.domain.ids import ReconciliationSessionId, ResidualDocumentId, TechnicianId
from src.domain.technician_settlement.aggregate import CompleteReconciliationSession
from src.domain.technician_settlement.residual_document import (
    ReconciliationResidualDocument,
    residual_kind_for,
)


@beartype
@dataclass(frozen=True, slots=True)
class DraftPlanMaps:
    period_ids: tuple[str, ...]
    deferred_period_ids: tuple[str, ...]
    transfer_refs: tuple[ImportedTransferRef, ...]
    warehouse_delta_by_sku: dict[str, Decimal]
    ledger_balance_before: dict[str, Decimal]
    residual_by_sku: dict[str, Decimal]
    calculated_stock_by_sku: dict[str, Decimal]
    actual_stock_by_sku: dict[str, Decimal]
    previous_actual_by_sku: dict[str, Decimal]
    supply_in_by_sku: dict[str, Decimal]
    returns_by_sku: dict[str, Decimal]
    loadings_by_sku: dict[str, Decimal]


@beartype
def unpack_draft_plan(
    plan: dict[str, Any],
    *,
    include_deferred: bool = True,
) -> DraftPlanMaps:
    return DraftPlanMaps(
        period_ids=plan_str_tuple(plan, "period_ids"),
        deferred_period_ids=(
            plan_str_tuple(plan, "deferred_period_ids") if include_deferred else ()
        ),
        transfer_refs=tuple(
            ImportedTransferRef(doc_id, content_hash)
            for doc_id, content_hash in plan_transfer_refs(plan)
        ),
        warehouse_delta_by_sku=plan_money_map(plan, "warehouse_delta_by_sku"),
        ledger_balance_before=plan_money_map(plan, "ledger_balance_before"),
        residual_by_sku=plan_money_map(plan, "residual_by_sku"),
        calculated_stock_by_sku=plan_money_map(plan, "calculated_stock_by_sku"),
        actual_stock_by_sku=plan_money_map(plan, "actual_stock_by_sku"),
        previous_actual_by_sku=plan_money_map(plan, "previous_actual_by_sku"),
        supply_in_by_sku=plan_money_map(plan, "supply_in_by_sku"),
        returns_by_sku=plan_money_map(plan, "returns_by_sku"),
        loadings_by_sku=plan_money_map(plan, "loadings_by_sku"),
    )


@beartype
def maybe_create_residual(
    *,
    residual_repo: ReconciliationResidualDocumentRepository,
    technician_id: TechnicianId,
    command: CompleteReconciliationSession,
) -> None:
    kind = residual_kind_for(command.residual_by_sku)
    if kind is None:
        return
    residual_repo.save(
        ReconciliationResidualDocument(
            residual_document_id=ResidualDocumentId(
                f"{command.session_id.value}:{uuid.uuid4()}",
            ),
            session_id=command.session_id,
            technician_id=technician_id,
            kind=kind,
            residual_by_sku=command.residual_by_sku,
            created_at=datetime.now(tz=UTC),
        ),
    )


@beartype
def persist_empty_scope_residual(
    *,
    residual_repo: ReconciliationResidualDocumentRepository,
    technician_id: TechnicianId,
    warehouse_inventory_id: str,
    residual_by_sku: dict[str, Decimal],
) -> bool:
    """Persist residual for empty-scope auto-reconcile; idempotent per inventory."""
    kind = residual_kind_for(residual_by_sku)
    if kind is None:
        return False
    session_id = ReconciliationSessionId(
        f"empty-scope:{technician_id.value}:{warehouse_inventory_id}",
    )
    residual_repo.save(
        ReconciliationResidualDocument(
            residual_document_id=ResidualDocumentId(f"{session_id.value}:residual"),
            session_id=session_id,
            technician_id=technician_id,
            kind=kind,
            residual_by_sku=dict(residual_by_sku),
            created_at=datetime.now(tz=UTC),
        ),
    )
    return True
