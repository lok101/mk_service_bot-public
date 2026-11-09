from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.ports import (
    CompleteMaintenanceInventoryGate,
    EventStore,
    LoadingFormLinkProvider,
    MaintenanceCooldownBypassReader,
    RevisionFormLinkProvider,
    TechnicianLastMaintenanceProjection,
    VendingMachineRepository,
)
from src.application.machine_operations.services import (
    CompleteMaintenanceService,
    CreateLoadingFormService,
    GetServiceCapabilitiesService,
    GetTechnicianRevisionOutlookService,
    ListAvailableMachinesService,
)
from src.application.micromarket_loading import MicromarketLoadingCycleStore
from src.application.micromarket_loading.ports import MicromarketAssemblyOrderStore
from src.infrastructure.memory import EventSourcedMachineOperationsRepository
from src.infrastructure.micromarket_loading.supply_order_category_sync_worker import (
    SupplyOrderCategoryFactsSyncWorker,
)
from src.infrastructure.micromarket_loading.warehouse_stock_sync_worker import (
    MicromarketWarehouseStockSyncWorker,
)
from src.infrastructure.micromarket_loading_alert_worker import MicromarketLoadingAlertWorker


@beartype
@dataclass(frozen=True, slots=True)
class MachineOpsBundle:
    event_store: EventStore
    repository: EventSourcedMachineOperationsRepository
    executor: MachineOperationsExecutor
    technician_last_maintenance: TechnicianLastMaintenanceProjection
    vending_machines: VendingMachineRepository
    revision_form_links: RevisionFormLinkProvider
    loading_form_links: LoadingFormLinkProvider
    list_available_machines: ListAvailableMachinesService
    get_service_capabilities: GetServiceCapabilitiesService
    get_technician_revision_outlook: GetTechnicianRevisionOutlookService
    complete_maintenance: CompleteMaintenanceService
    create_loading_form: CreateLoadingFormService
    maintenance_cooldown_bypass: MaintenanceCooldownBypassReader
    service_calendar_timezone: ZoneInfo
    maintenance_cooldown_minutes: int
    inventory_gate: CompleteMaintenanceInventoryGate | None = None
    micromarket_loading_cycle_store: MicromarketLoadingCycleStore | None = None
    micromarket_assembly_order_store: MicromarketAssemblyOrderStore | None = None
    micromarket_loading_alert_worker: MicromarketLoadingAlertWorker | None = None
    micromarket_warehouse_stock_sync_worker: MicromarketWarehouseStockSyncWorker | None = None
    supply_order_category_facts_sync_worker: SupplyOrderCategoryFactsSyncWorker | None = None
