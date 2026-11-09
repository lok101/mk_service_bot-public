from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.machine_operations.ports import TechnicianWarehouseInventoryLinkProvider
from src.application.technician_warehouse import (
    AcceptTechnicianWarehouseInventoryService,
    CloseTechnicianWarehouse,
    ImportTechnicianWarehouseTransfers,
    ObserveTechnicianWarehouseLoading,
    TechnicianWarehouseDeltaPort,
    TechnicianWarehouseEventStore,
    TechnicianWarehouseExecutor,
)


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseBundle:
    executor: TechnicianWarehouseExecutor
    event_store: TechnicianWarehouseEventStore
    importer: ImportTechnicianWarehouseTransfers
    delta_port: TechnicianWarehouseDeltaPort
    accept_inventory: AcceptTechnicianWarehouseInventoryService
    link_provider: TechnicianWarehouseInventoryLinkProvider
    observe_loading: ObserveTechnicianWarehouseLoading
    close_warehouse: CloseTechnicianWarehouse
