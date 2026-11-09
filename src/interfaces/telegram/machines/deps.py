from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.machine_operations import (
    CompleteMaintenance,
    CreateLoadingForm,
    GetServiceCapabilities,
    ListAvailableMachines,
)
from src.application.machine_operations.ports import (
    MachineOperationsRepository,
    TechnicianWarehouseInventoryLinkProvider,
    VendingMachineRepository,
)
from src.application.micromarket_loading.issue_inventory_link import IssueMicromarketInventoryLink
from src.application.micromarket_loading.ports import (
    MachineKindLookup,
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
)
from src.application.photo_batches import AcceptLoadingPhotosService
from src.application.photo_batches.loading_photos_limits import LoadingPhotosProfileLookup
from src.application.product_identity.ports import DomainProductStore
from src.application.service_visits.ports import ServiceVisitStore
from src.application.snack_loading.issue_inventory_link import IssueSnackInventoryLink
from src.application.snack_loading.ports import SnackInventoryCellsSource
from src.interfaces.admin.deps import KitProductGroupsLoad
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore


@beartype
@dataclass(frozen=True, slots=True)
class MachineDialogDeps:
    telegram_user_resolver: TelegramUserResolver
    technician_warehouse_inventory_link_provider: TechnicianWarehouseInventoryLinkProvider


@beartype
@dataclass(frozen=True, slots=True)
class MachineListDeps:
    service_display_timezone: ZoneInfo
    service_day_end_hour: int
    visit_store: ServiceVisitStore
    telegram_user_resolver: TelegramUserResolver
    vending_machine_repository: VendingMachineRepository
    machine_operations: MachineOperationsRepository
    list_available_machines: ListAvailableMachines
    get_service_capabilities: GetServiceCapabilities
    complete_maintenance: CompleteMaintenance
    create_loading_form: CreateLoadingForm
    form_workflow_sessions: FormWorkflowSessionStore
    accept_loading_photos: AcceptLoadingPhotosService
    loading_photos_min_count: int
    loading_photos_max_count: int
    maintenance_cooldown_minutes: int
    issue_snack_inventory_link: IssueSnackInventoryLink | None = None
    snack_inventory_cells: SnackInventoryCellsSource | None = None
    issue_micromarket_inventory_link: IssueMicromarketInventoryLink | None = None
    micromarket_planogram_store: MicromarketPlanogramStore | None = None
    micromarket_stock_store: MicromarketDeviceStockStore | None = None
    machine_kind_lookup: MachineKindLookup | None = None
    loading_photos_profile_lookup: LoadingPhotosProfileLookup | None = None
    visit_photo_profile_strict: bool = False
    domain_product_store: DomainProductStore | None = None
    load_kit_product_groups: Callable[[], KitProductGroupsLoad] | None = None
