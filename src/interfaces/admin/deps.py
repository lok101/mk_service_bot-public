from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple
from uuid import UUID
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_inventory_policy import FormInventoryPolicyStore
from src.application.inventory_reconciliation import MachineCompanyOccupancyStore
from src.application.master_data import (
    CoffeeMachineModelStore,
    CompanyStore,
    CreateCompany,
    CreateTechnician,
    MasterDataExportHook,
    MasterDataStores,
    SaveFieldStaff,
    SaveSystemUsers,
    StandColorStore,
    StandTypeStore,
    SystemUserStore,
    TechnicianStore,
    UpdateCompany,
    UpdateTechnician,
)
from src.application.matrix_automation import ApplySnackMatrix
from src.application.matrix_automation.ports import (
    MatrixBaseMarginStore,
    MatrixPriceSnapshotStore,
    MatrixSkuCatalogStore,
    PurchaseAttributesReader,
    SnackMachineLayoutStore,
)
from src.application.micromarket_loading import (
    MicromarketDeviceStockStore,
    MicromarketLoadingCycleStore,
    MicromarketMoveGateway,
    MicromarketPlanogramStore,
    MicromarketSupplyOrderStore,
)
from src.application.micromarket_loading.ports import (
    DetachVisitTaskOnLoadingRollbackPort,
    EnsureOpenVisitTaskPort,
    MicromarketAssemblyOrderStore,
    MicromarketMachineMultiplierStore,
    MicromarketPriceChangeJournal,
    MicromarketPricingRulesStore,
    MicromarketProductMultiplierStore,
    MicromarketWarehouseStockSnapshotPort,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
    SupplyOrderCategoryFactsPort,
    SupplyOrderDemandForecastPort,
)
from src.application.photo_batches import PhotoStorage
from src.application.product_identity import SyncProcurementMirror
from src.application.product_identity.ports import (
    CatalogProductLookup,
    DomainProductStore,
    ProcurementMirrorStore,
)
from src.application.reference_data import (
    LocationRosterDraftStore,
    LocationRosterStore,
    ReferenceDataProvider,
    ReferenceDataSnapshotStore,
)
from src.application.reference_data.ports import ProductCatalogMsAssortmentReader
from src.application.service_visits import (
    BuildVisitBoardMonth,
    MaintenanceOnOperationalDayLookup,
    ServiceVisitStore,
)
from src.application.shared import AdminNavStructureStore
from src.application.snack_loading import SnackMachineStockStore
from src.application.technician_settlement import (
    AggregateSettlementClusters,
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
    BuildSettlementAnalysisTree,
    SettlementAnalysisPrefsStore,
)
from src.application.visit_photo_grouping import DisposeUnrecognizedIndex
from src.application.visit_photo_review import (
    ClearReviewRecord,
    ReviewQueries,
    SaveReviewRecord,
    SaveVisitPhotoProfile,
    UpdateGroupDefects,
    VisitPhotoProfileStore,
    VisitPhotoProfileTechRefStorage,
    WriteGroupAvatar,
)
from src.application.visit_photo_review.ports import GroupAvatarReader, ReviewLabelLookup
from src.domain.ids import MachineId


class KitProductGroupsLoad(NamedTuple):
    error: str
    groups: tuple[tuple[int, str], ...]
    warning: str = ""


def _default_load_kit_product_groups() -> KitProductGroupsLoad:
    return KitProductGroupsLoad(error="Группы Kit Shop не загрузились", groups=())


@beartype
@dataclass(frozen=True, slots=True)
class AdminHttpDeps:
    provider: ReferenceDataProvider
    roster_store: LocationRosterStore
    roster_draft_store: LocationRosterDraftStore
    visit_store: ServiceVisitStore
    maintenance_lookup: MaintenanceOnOperationalDayLookup
    bot_token: str
    session_secret: str
    session_ttl_seconds: int
    telegram_auth_max_age_seconds: int
    telegram_bot_username: str
    stub_login_enabled: bool
    timezone: ZoneInfo
    day_end_hour: int
    now_factory: Callable[[], datetime]
    admin_max_body_bytes: int = 1_048_576
    master_stores: MasterDataStores | None = None
    coffee_machine_model_store: CoffeeMachineModelStore | None = None
    stand_type_store: StandTypeStore | None = None
    stand_color_store: StandColorStore | None = None
    master_data_export_hook: MasterDataExportHook | None = None
    build_visit_board: BuildVisitBoardMonth | None = None
    users_enabled: bool = False
    system_user_store: SystemUserStore | None = None
    save_system_users: SaveSystemUsers | None = None
    save_field_staff: SaveFieldStaff | None = None
    technicians_enabled: bool = False
    technician_store: TechnicianStore | None = None
    create_technician: CreateTechnician | None = None
    update_technician: UpdateTechnician | None = None
    companies_enabled: bool = False
    company_store: CompanyStore | None = None
    create_company: CreateCompany | None = None
    update_company: UpdateCompany | None = None
    refresh_company_display_names: Callable[[], None] | None = None
    layout_master_enabled: bool = False
    snack_layout_store: SnackMachineLayoutStore | None = None
    matrix_price_snapshot_store: MatrixPriceSnapshotStore | None = None
    purchase_attributes_reader: PurchaseAttributesReader | None = None
    snack_stock_store: SnackMachineStockStore | None = None
    matrix_multiplier_min: Decimal = Decimal("0.8")
    matrix_multiplier_max: Decimal = Decimal("3.0")
    sku_catalog_master_enabled: bool = False
    matrix_sku_catalog_store: MatrixSkuCatalogStore | None = None
    matrix_base_margin_store: MatrixBaseMarginStore | None = None
    apply_snack_matrix: ApplySnackMatrix | None = None
    scale_price_min_bound: Decimal = Decimal("10")
    scale_price_max_bound: Decimal = Decimal("500")
    scale_rate_min_bound: Decimal = Decimal("0.1")
    scale_rate_max_bound: Decimal = Decimal("2.0")
    curvature_min: Decimal = Decimal("0.5")
    curvature_max: Decimal = Decimal("3")
    margin_floor_min: Decimal = Decimal("10")
    margin_floor_max: Decimal = Decimal("100")
    snack_sku_assortment_reader: ProductCatalogMsAssortmentReader | None = None
    snack_sku_folder_ids: tuple[UUID, ...] = ()
    settlement_analysis_enabled: bool = False
    build_settlement_analysis_tree: BuildSettlementAnalysisTree | None = None
    aggregate_settlement_clusters: AggregateSettlementClusters | None = None
    build_session_analysis_view: BuildSessionAnalysisView | None = None
    build_period_analysis_view: BuildPeriodAnalysisView | None = None
    settlement_analysis_prefs_store: SettlementAnalysisPrefsStore | None = None
    visit_photo_review_enabled: bool = False
    review_queries: ReviewQueries | None = None
    save_review_record: SaveReviewRecord | None = None
    clear_review_record: ClearReviewRecord | None = None
    dispose_unrecognized_index: DisposeUnrecognizedIndex | None = None
    review_label_lookup: ReviewLabelLookup | None = None
    group_avatar_reader: GroupAvatarReader | None = None
    update_group_defects: UpdateGroupDefects | None = None
    write_group_avatar: WriteGroupAvatar | None = None
    photo_storage: PhotoStorage | None = None
    visit_photo_profile_store: VisitPhotoProfileStore | None = None
    save_visit_photo_profile: SaveVisitPhotoProfile | None = None
    visit_photo_profile_tech_ref_storage: VisitPhotoProfileTechRefStorage | None = None
    admin_nav_structure_store: AdminNavStructureStore | None = None
    company_occupancy_store: MachineCompanyOccupancyStore | None = None
    company_display_names: dict[int, str] | None = None
    micromarket_planogram_store: MicromarketPlanogramStore | None = None
    micromarket_pricing_rules_store: MicromarketPricingRulesStore | None = None
    micromarket_product_multiplier_store: MicromarketProductMultiplierStore | None = None
    micromarket_machine_multiplier_store: MicromarketMachineMultiplierStore | None = None
    micromarket_price_change_journal: MicromarketPriceChangeJournal | None = None
    micromarket_margin_percent_min: Decimal = Decimal("20")
    micromarket_margin_percent_max: Decimal = Decimal("100")
    micromarket_margin_floor_min: Decimal = Decimal("20")
    micromarket_margin_floor_max: Decimal = Decimal("100")
    micromarket_product_multiplier_min: Decimal = Decimal("0.8")
    micromarket_product_multiplier_max: Decimal = Decimal("3.0")
    micromarket_machine_multiplier_min: Decimal = Decimal("0.8")
    micromarket_machine_multiplier_max: Decimal = Decimal("3.0")
    micromarket_max_price_delta_pct: Decimal = Decimal("15")
    micromarket_stock_store: MicromarketDeviceStockStore | None = None
    shop_list_publish_journal: ShopListPublishJournal | None = None
    shop_list_baseline_store: ShopListLastSucceededSnapshotStore | None = None
    micromarket_ms_product_folder_ids: tuple[UUID, ...] = ()
    # Path listing for enroll picker; not gated by MATRIX_SKU_CATALOG_MASTER_ENABLED.
    micromarket_assortment_reader: ProductCatalogMsAssortmentReader | None = None
    micromarket_loading_cycle_store: MicromarketLoadingCycleStore | None = None
    micromarket_assembly_order_store: MicromarketAssemblyOrderStore | None = None
    micromarket_supply_order_store: MicromarketSupplyOrderStore | None = None
    supply_order_category_facts: SupplyOrderCategoryFactsPort | None = None
    supply_order_demand_forecast: SupplyOrderDemandForecastPort | None = None
    supply_order_snacks_folder_id: str = ""
    supply_order_ready_meals_folder_id: str = ""
    supply_order_shelf_life_days_threshold: int = 7
    micromarket_loading_execute_enabled: bool = False
    micromarket_loading_warehouse_gate_enabled: bool = True
    micromarket_loading_move_gateway: MicromarketMoveGateway | None = None
    micromarket_warehouse_stock_snapshot: MicromarketWarehouseStockSnapshotPort | None = None
    micromarket_warehouse_stock_cold_wait_seconds: int = 15
    ensure_open_visit_task: EnsureOpenVisitTaskPort | None = None
    detach_visit_on_loading_rollback: DetachVisitTaskOnLoadingRollbackPort | None = None
    load_kit_product_groups: Callable[[], KitProductGroupsLoad] = field(
        default=_default_load_kit_product_groups,
    )
    micromarket_shop_list_publisher: object | None = None
    domain_product_store: DomainProductStore | None = None
    form_inventory_policy_store: FormInventoryPolicyStore | None = None
    coffee_recipe_repo: CoffeeRecipeRepository | None = None
    refresh_pending_after_bom: Callable[[], None] | None = None
    border_registration_store: object | None = None
    catalog_product_lookup: CatalogProductLookup | None = None
    catalog_snapshot_store: ReferenceDataSnapshotStore | None = None
    product_catalog_sync: Callable[[], Awaitable[None]] | None = None
    procurement_mirror_enabled: bool = False
    procurement_mirror_store: ProcurementMirrorStore | None = None
    procurement_sync: SyncProcurementMirror | None = None
    list_open_no_sales: Callable[[], list[dict[str, object]]] | None = None
    list_open_offline: Callable[[], list[dict[str, object]]] | None = None
    list_no_sales_controls: Callable[[MachineId], list[dict[str, object]]] | None = None
    list_cleared_no_sales_since: Callable[..., list[dict[str, object]]] | None = None
    list_no_sales_episodes_overlapping: Callable[..., list[dict[str, object]]] | None = None
    list_maintenance_completed_in_completed_at_window: Callable[..., tuple[object, ...]] | None = (
        None
    )
    incident_clear_pair_minutes: int | None = None
    enqueue_no_sales_incident_control: Callable[..., None] | None = None
