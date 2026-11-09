from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.technician_warehouse.errors import MoySkladUnavailable
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.application.technician_warehouse.ports import (
    ImportedTransferRef,
    TechnicianWarehouseDelta,
    TechnicianWarehouseDeltaPort,
    UnmatchedMsProduct,
)
from src.domain.ids import TechnicianId

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class TechnicianWarehouseDeltaService(TechnicianWarehouseDeltaPort):
    importer: ImportTechnicianWarehouseTransfers
    executor: TechnicianWarehouseExecutor

    @beartype
    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> TechnicianWarehouseDelta | None:
        transfer_refs: tuple[ImportedTransferRef, ...] = ()
        unmatched_products: tuple[UnmatchedMsProduct, ...] = ()
        if not skip_import:
            try:
                import_result = await self.importer.execute(technician_id, anchor_at=until)
            except MoySkladUnavailable:
                raise
            transfer_refs = import_result.transfer_refs
            unmatched_products = import_result.unmatched_products

        warehouse = self.executor.repository.get(technician_id)
        domain_delta = warehouse.compute_warehouse_delta_between_latest_inventories()
        if domain_delta is None:
            return None
        if after is not None and domain_delta.previous_inventory_moment < after:
            return None

        _LOGGER.info(
            "technician_warehouse_delta_planned technician_id=%s inventory_id=%s skip_import=%s",
            technician_id.value,
            domain_delta.current_inventory_id,
            skip_import,
        )
        return TechnicianWarehouseDelta(
            warehouse_inventory_id=domain_delta.current_inventory_id,
            inventory_moment=domain_delta.current_inventory_moment,
            warehouse_delta_by_sku=dict(domain_delta.delta_by_sku),
            calculated_stock_by_sku=dict(domain_delta.calculated_by_sku),
            actual_stock_by_sku=dict(domain_delta.actual_by_sku),
            transfer_refs=transfer_refs,
            unmatched_products=unmatched_products,
            previous_actual_by_sku=dict(domain_delta.previous_actual_by_sku),
            supply_in_by_sku=dict(domain_delta.supply_in_by_sku),
            returns_by_sku=dict(domain_delta.returns_by_sku),
            loadings_by_sku=dict(domain_delta.loadings_by_sku),
        )
