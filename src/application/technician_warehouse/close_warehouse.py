from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.technician_warehouse.errors import (
    CloseTechnicianWarehouseError,
    WarehouseAlreadyClosed,
)
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    TechnicianWarehouseImportResult,
)
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse import (
    TechnicianWarehouse,
    TechnicianWarehouseDelta,
    TechnicianWarehouseExitClosed,
    TechnicianWarehouseTransferObserved,
    TransferDirection,
)

_logger = logging.getLogger(__name__)


@runtime_checkable
class _TransferImporter(Protocol):
    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult: ...


@beartype
@dataclass(frozen=True, slots=True)
class CloseWarehouseDryRunReport:
    technician_id: TechnicianId
    closed_at: datetime
    return_external_document_id: str
    return_content_hash: str
    planned_delta_by_sku: dict[str, Decimal]
    previous_inventory_id: str


@beartype
@dataclass(frozen=True, slots=True)
class CloseTechnicianWarehouse:
    executor: TechnicianWarehouseExecutor
    importer: _TransferImporter

    @beartype
    async def execute(
        self,
        *,
        technician_id: TechnicianId,
        closed_at: datetime | None = None,
        confirm: bool,
    ) -> TechnicianWarehouseExitClosed | CloseWarehouseDryRunReport:
        resolved_closed_at = closed_at or datetime.now(tz=UTC)
        warehouse = self.executor.repository.get(technician_id)
        if warehouse.is_closed():
            raise WarehouseAlreadyClosed(technician_id)

        await self.importer.execute(technician_id, anchor_at=resolved_closed_at)
        warehouse = self.executor.repository.get(technician_id)
        last = _last_non_voided_transfer(warehouse)
        if last is None or last.direction is not TransferDirection.SUPPLY_RETURN:
            raise CloseTechnicianWarehouseError(
                "last transfer must be SUPPLY_RETURN before exit close",
            )
        if not confirm:
            preview = _preview_close(
                warehouse,
                closed_at=resolved_closed_at,
                return_external_document_id=last.external_document_id,
                return_content_hash=last.content_hash,
            )
            return CloseWarehouseDryRunReport(
                technician_id=technician_id,
                closed_at=resolved_closed_at,
                return_external_document_id=last.external_document_id,
                return_content_hash=last.content_hash,
                planned_delta_by_sku=dict(preview.delta_by_sku),
                previous_inventory_id=preview.previous_inventory_id,
            )

        def _cmd(agg: TechnicianWarehouse) -> TechnicianWarehouseExitClosed:
            return agg.close_exit(
                closed_at=resolved_closed_at,
                return_external_document_id=last.external_document_id,
                return_content_hash=last.content_hash,
            )

        event = self.executor.execute(technician_id, _cmd)
        delta = self.executor.repository.get(technician_id).latest_warehouse_delta()
        previous_id = delta.previous_inventory_id if delta is not None else ""
        _logger.info(
            "technician_warehouse_exit_closed technician_id=%s return_id=%s "
            "closed_at=%s event_id=%s previous_inventory_id=%s",
            technician_id.value,
            event.return_external_document_id,
            event.closed_at.isoformat(),
            event.event_id.value,
            previous_id,
        )
        return event


@beartype
def _last_non_voided_transfer(
    warehouse: TechnicianWarehouse,
) -> TechnicianWarehouseTransferObserved | None:
    transfers = warehouse.non_voided_transfers()
    if not transfers:
        return None
    return max(
        transfers,
        key=lambda t: (t.moment, t.updated_at, t.observed_at, t.external_document_id),
    )


@beartype
def _preview_close(
    warehouse: TechnicianWarehouse,
    *,
    closed_at: datetime,
    return_external_document_id: str,
    return_content_hash: str,
) -> TechnicianWarehouseDelta:
    # Aggregate from repository.get() is ephemeral; mutate without save.
    warehouse.close_exit(
        closed_at=closed_at,
        return_external_document_id=return_external_document_id,
        return_content_hash=return_content_hash,
    )
    delta = warehouse.latest_warehouse_delta()
    if delta is None:
        raise CloseTechnicianWarehouseError("exit close preview produced no warehouse delta")
    return delta
