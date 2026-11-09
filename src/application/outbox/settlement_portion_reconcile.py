from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.outbox.finalized_transfer_drift_ops import (
    FinalizedTransferDriftOpsAlerter,
    NoOpFinalizedTransferDriftOpsAlerter,
)
from src.application.outbox.handler_ids import SETTLEMENT_PORTION_RECONCILE_HANDLER_ID
from src.application.outbox.settlement_portion_sales_verify import PortionSalesVerifier
from src.application.outbox.settlement_portion_sync_transfers import PortionTransfersImporter
from src.application.technician_settlement import (
    EmptyReconcileScope,
    ReconciliationBlocked,
    ReconciliationPreview,
    ReconciliationResidualDocumentRepository,
    persist_empty_scope_residual,
)
from src.domain.events import DomainEvent
from src.domain.ids import TechnicianId
from src.domain.technician_settlement.portion_events import SettlementPortionReconcileRequested

_LOGGER = logging.getLogger(__name__)

_EMPTY_SCOPE_BLOCKER = "nothing to reconcile in window"


@runtime_checkable
class PortionReconcilePreview(Protocol):
    def build_preview_for_inventory(
        self,
        *,
        technician_id: TechnicianId,
        warehouse_inventory_id: str,
        skip_import: bool = True,
    ) -> ReconciliationPreview: ...


@runtime_checkable
class PortionReconcileFinalize(Protocol):
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> object: ...


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionReconcileHandler:
    preview: PortionReconcilePreview
    finalize: PortionReconcileFinalize
    importer: PortionTransfersImporter
    verifier: PortionSalesVerifier
    residual_repo: ReconciliationResidualDocumentRepository
    drift_ops_alerter: FinalizedTransferDriftOpsAlerter = NoOpFinalizedTransferDriftOpsAlerter()

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, SettlementPortionReconcileRequested):
            raise NonRetryableOutboxError(
                f"Unsupported settlement portion reconcile event: {type(event).__name__}",
            )
        import_result = await self.importer.execute(
            event.technician_id,
            anchor_at=event.warehouse_inventory_moment,
        )
        if import_result.ignored_finalized_transfers:
            try:
                self.drift_ops_alerter.notify_drift(
                    technician_id=event.technician_id.value,
                    items=import_result.ignored_finalized_transfers,
                )
            except Exception:
                _LOGGER.warning(
                    "finalized_transfer_drift_ops notify failed technician_id=%s",
                    event.technician_id.value,
                    exc_info=True,
                )
        _LOGGER.info(
            "settlement_portion_reconcile_resync_transfers technician_id=%s "
            "warehouse_inventory_id=%s imported=%s updated=%s voided=%s",
            event.technician_id.value,
            event.warehouse_inventory_id,
            import_result.imported,
            import_result.updated,
            import_result.voided,
        )
        verify_result = self.verifier.execute(
            technician_id=event.technician_id,
            cutoff=event.warehouse_inventory_moment,
        )
        _LOGGER.info(
            "settlement_portion_reconcile_resync_sales_verify technician_id=%s "
            "warehouse_inventory_id=%s result=%s",
            event.technician_id.value,
            event.warehouse_inventory_id,
            verify_result,
        )
        try:
            preview = self.preview.build_preview_for_inventory(
                technician_id=event.technician_id,
                warehouse_inventory_id=event.warehouse_inventory_id,
                skip_import=True,
            )
        except EmptyReconcileScope as exc:
            persisted = persist_empty_scope_residual(
                residual_repo=self.residual_repo,
                technician_id=event.technician_id,
                warehouse_inventory_id=exc.warehouse_inventory_id,
                residual_by_sku=exc.residual_by_sku,
            )
            _LOGGER.info(
                "portion_reconcile_empty_scope technician_id=%s warehouse_inventory_id=%s "
                "residual_persisted=%s",
                event.technician_id.value,
                event.warehouse_inventory_id,
                persisted,
            )
            return
        except ReconciliationBlocked as exc:
            if str(exc) == _EMPTY_SCOPE_BLOCKER:
                _LOGGER.info(
                    "portion_reconcile_empty_scope technician_id=%s warehouse_inventory_id=%s",
                    event.technician_id.value,
                    event.warehouse_inventory_id,
                )
                return
            raise
        if not preview.can_finalize:
            raise RuntimeError(f"portion reconcile blocked: {preview.blockers}")
        if preview.warehouse_inventory_id != event.warehouse_inventory_id:
            raise RuntimeError(
                "portion reconcile inventory mismatch: "
                f"preview={preview.warehouse_inventory_id} event={event.warehouse_inventory_id}",
            )
        self.finalize.execute(technician_id=event.technician_id)
        _LOGGER.info(
            "settlement_portion_reconcile_completed technician_id=%s warehouse_inventory_id=%s",
            event.technician_id.value,
            event.warehouse_inventory_id,
        )


__all__ = [
    "SETTLEMENT_PORTION_RECONCILE_HANDLER_ID",
    "SettlementPortionReconcileHandler",
]
