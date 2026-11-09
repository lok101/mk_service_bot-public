from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.outbox.border_unregistered_ops import (
    BorderUnregisteredOpsAlerter,
    NoOpBorderUnregisteredOpsAlerter,
)
from src.application.outbox.finalized_transfer_drift_ops import (
    FinalizedTransferDriftOpsAlerter,
    NoOpFinalizedTransferDriftOpsAlerter,
)
from src.application.outbox.handler_ids import SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID
from src.application.technician_settlement import enqueue_portion_sales_verify
from src.application.technician_warehouse import (
    TechnicianWarehouseImportBlocked,
    TechnicianWarehouseImportResult,
)
from src.domain.events import DomainEvent
from src.domain.ids import TechnicianId
from src.domain.technician_settlement.portion_events import SettlementPortionSyncTransfersRequested

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class PortionTransfersImporter(Protocol):
    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult: ...


@runtime_checkable
class PortionEventPublisher(Protocol):
    def publish(self, event: DomainEvent) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionSyncTransfersHandler:
    importer: PortionTransfersImporter
    publisher: PortionEventPublisher
    border_ops_alerter: BorderUnregisteredOpsAlerter = NoOpBorderUnregisteredOpsAlerter()
    drift_ops_alerter: FinalizedTransferDriftOpsAlerter = NoOpFinalizedTransferDriftOpsAlerter()

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, SettlementPortionSyncTransfersRequested):
            raise NonRetryableOutboxError(
                f"Unsupported settlement portion sync event: {type(event).__name__}",
            )
        try:
            result = await self.importer.execute(
                event.technician_id,
                anchor_at=event.warehouse_inventory_moment,
            )
        except TechnicianWarehouseImportBlocked as blocked:
            if blocked.unregistered_products:
                self.border_ops_alerter.notify_unregistered(
                    technician_id=blocked.technician_id or event.technician_id.value,
                    products=blocked.unregistered_products,
                )
            raise
        if result.ignored_finalized_transfers:
            try:
                self.drift_ops_alerter.notify_drift(
                    technician_id=event.technician_id.value,
                    items=result.ignored_finalized_transfers,
                )
            except Exception:
                _LOGGER.warning(
                    "finalized_transfer_drift_ops notify failed technician_id=%s",
                    event.technician_id.value,
                    exc_info=True,
                )
        _LOGGER.info(
            "settlement_portion_sync_transfers_completed technician_id=%s "
            "warehouse_inventory_id=%s imported=%s updated=%s voided=%s ignored=%s "
            "skipped_unresolved=%s truncated_non_domain=%s",
            event.technician_id.value,
            event.warehouse_inventory_id,
            result.imported,
            result.updated,
            result.voided,
            result.ignored,
            result.skipped_unresolved,
            result.truncated_non_domain,
        )
        enqueue_portion_sales_verify(
            publisher=self.publisher,
            technician_id=event.technician_id,
            warehouse_inventory_id=event.warehouse_inventory_id,
            warehouse_inventory_moment=event.warehouse_inventory_moment,
        )


__all__ = [
    "SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID",
    "SettlementPortionSyncTransfersHandler",
]
