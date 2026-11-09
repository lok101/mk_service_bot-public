from __future__ import annotations

from beartype import beartype
from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase

MONGODB_HEALTHCHECK_TIMEOUT_MS = 5000


class MongoSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    uri: str | None = Field(default=None, validation_alias="MONGODB_URI")
    database: str = Field(default="mk_service_bot", validation_alias="MONGODB_DATABASE")
    events_collection: str = Field(
        default="machine_events",
        validation_alias="MONGODB_EVENTS_COLLECTION",
    )
    outbox_collection: str = Field(
        default="domain_event_outbox",
        validation_alias="MONGODB_OUTBOX_COLLECTION",
    )
    form_submissions_collection: str = Field(
        default="form_submissions",
        validation_alias="MONGODB_FORM_SUBMISSIONS_COLLECTION",
    )
    photo_batches_collection: str = Field(
        default="photo_batches",
        validation_alias="MONGODB_PHOTO_BATCHES_COLLECTION",
    )
    photo_content_hashes_collection: str = Field(
        default="photo_content_hashes",
        validation_alias="MONGODB_PHOTO_CONTENT_HASHES_COLLECTION",
    )
    photo_integrity_findings_collection: str = Field(
        default="photo_integrity_findings",
        validation_alias="MONGODB_PHOTO_INTEGRITY_FINDINGS_COLLECTION",
    )
    technician_accountability_events_collection: str = Field(
        default="technician_accountability_events",
        validation_alias="MONGODB_TECHNICIAN_ACCOUNTABILITY_EVENTS_COLLECTION",
    )
    form_workflow_sessions_collection: str = Field(
        default="form_workflow_sessions",
        validation_alias="MONGODB_FORM_WORKFLOW_SESSIONS_COLLECTION",
    )
    external_side_effects_collection: str = Field(
        default="external_side_effects",
        validation_alias="MONGODB_EXTERNAL_SIDE_EFFECTS_COLLECTION",
    )
    machine_sales_collection: str = Field(
        default="machine_sales",
        validation_alias="MONGODB_MACHINE_SALES_COLLECTION",
    )
    machine_sales_skipped_collection: str = Field(
        default="machine_sales_skipped",
        validation_alias="MONGODB_MACHINE_SALES_SKIPPED_COLLECTION",
        min_length=1,
    )
    machine_company_occupancy_collection: str = Field(
        default="machine_company_occupancy",
        validation_alias="MONGODB_MACHINE_COMPANY_OCCUPANCY_COLLECTION",
        min_length=1,
    )
    coffee_recipes_collection: str = Field(
        default="coffee_recipes",
        validation_alias="MONGODB_COFFEE_RECIPES_COLLECTION",
    )
    responsibility_period_reconciliations_collection: str = Field(
        default="responsibility_period_reconciliations",
        validation_alias="MONGODB_RESPONSIBILITY_PERIOD_RECONCILIATIONS_COLLECTION",
    )
    reconciliation_residual_documents_collection: str = Field(
        default="reconciliation_residual_documents",
        validation_alias="MONGODB_RECONCILIATION_RESIDUAL_DOCUMENTS_COLLECTION",
    )
    technician_settlement_events_collection: str = Field(
        default="technician_settlement_events",
        validation_alias="MONGODB_TECHNICIAN_SETTLEMENT_EVENTS_COLLECTION",
    )
    technician_warehouse_events_collection: str = Field(
        default="technician_warehouse_events",
        validation_alias="MONGODB_TECHNICIAN_WAREHOUSE_EVENTS_COLLECTION",
    )
    reconciliation_drafts_collection: str = Field(
        default="reconciliation_drafts",
        validation_alias="MONGODB_RECONCILIATION_DRAFTS_COLLECTION",
        min_length=1,
    )
    reference_data_snapshots_collection: str = Field(
        default="reference_data_snapshots",
        validation_alias="MONGODB_REFERENCE_DATA_SNAPSHOTS_COLLECTION",
    )
    technician_last_maintenance_collection: str = Field(
        default="technician_last_maintenance",
        validation_alias="MONGODB_TECHNICIAN_LAST_MAINTENANCE_COLLECTION",
    )
    maintenance_cooldown_bypass_collection: str = Field(
        default="maintenance_cooldown_bypass",
        validation_alias="MONGODB_MAINTENANCE_COOLDOWN_BYPASS_COLLECTION",
    )
    snack_machine_stock_events_collection: str = Field(
        default="snack_machine_stock_events",
        validation_alias="MONGODB_SNACK_MACHINE_STOCK_EVENTS_COLLECTION",
    )
    micromarket_stock_events_collection: str = Field(
        default="micromarket_stock_events",
        validation_alias="MONGODB_MICROMARKET_STOCK_EVENTS_COLLECTION",
        min_length=1,
    )
    micromarket_planograms_collection: str = Field(
        default="micromarket_planograms",
        validation_alias="MONGODB_MICROMARKET_PLANOGRAMS_COLLECTION",
        min_length=1,
    )
    micromarket_pricing_rules_collection: str = Field(
        default="micromarket_pricing_rules",
        validation_alias="MONGODB_MICROMARKET_PRICING_RULES_COLLECTION",
        min_length=1,
    )
    micromarket_product_multipliers_collection: str = Field(
        default="micromarket_product_multipliers",
        validation_alias="MONGODB_MICROMARKET_PRODUCT_MULTIPLIERS_COLLECTION",
        min_length=1,
    )
    micromarket_machine_multipliers_collection: str = Field(
        default="micromarket_machine_multipliers",
        validation_alias="MONGODB_MICROMARKET_MACHINE_MULTIPLIERS_COLLECTION",
        min_length=1,
    )
    micromarket_price_change_journal_collection: str = Field(
        default="micromarket_price_change_journal",
        validation_alias="MONGODB_MICROMARKET_PRICE_CHANGE_JOURNAL_COLLECTION",
        min_length=1,
    )
    shop_list_publish_journal_collection: str = Field(
        default="shop_list_publish_journal",
        validation_alias="MONGODB_SHOP_LIST_PUBLISH_JOURNAL_COLLECTION",
        min_length=1,
    )
    micromarket_loading_order_events_collection: str = Field(
        default="micromarket_loading_order_events",
        validation_alias="MONGODB_MICROMARKET_LOADING_ORDER_EVENTS_COLLECTION",
        min_length=1,
    )
    micromarket_supply_orders_collection: str = Field(
        default="micromarket_supply_orders",
        validation_alias="MONGODB_MICROMARKET_SUPPLY_ORDERS_COLLECTION",
        min_length=1,
    )
    micromarket_warehouse_stock_snapshot_collection: str = Field(
        default="micromarket_warehouse_stock_snapshot",
        validation_alias="MONGODB_MICROMARKET_WAREHOUSE_STOCK_SNAPSHOT_COLLECTION",
        min_length=1,
    )
    micromarket_supply_order_category_snapshot_collection: str = Field(
        default="micromarket_supply_order_category_snapshot",
        validation_alias="MONGODB_MICROMARKET_SUPPLY_ORDER_CATEGORY_SNAPSHOT_COLLECTION",
        min_length=1,
    )
    micromarket_assembly_orders_collection: str = Field(
        default="micromarket_assembly_orders",
        validation_alias="MONGODB_MICROMARKET_ASSEMBLY_ORDERS_COLLECTION",
        min_length=1,
    )
    micromarket_pending_invent_collection: str = Field(
        default="micromarket_pending_invent",
        validation_alias="MONGODB_MICROMARKET_PENDING_INVENT_COLLECTION",
        min_length=1,
    )
    micromarket_loading_move_commands_collection: str = Field(
        default="micromarket_loading_move_commands",
        validation_alias="MONGODB_MICROMARKET_LOADING_MOVE_COMMANDS_COLLECTION",
        min_length=1,
    )
    kit_matrix_deploy_map_collection: str = Field(
        default="kit_matrix_deploy_map",
        validation_alias="MONGODB_KIT_MATRIX_DEPLOY_MAP_COLLECTION",
    )
    snack_inventory_form_registry_collection: str = Field(
        default="snack_inventory_form_registry",
        validation_alias="MONGODB_SNACK_INVENTORY_FORM_REGISTRY_COLLECTION",
    )
    micromarket_inventory_form_registry_collection: str = Field(
        default="micromarket_inventory_form_registry",
        validation_alias="MONGODB_MICROMARKET_INVENTORY_FORM_REGISTRY_COLLECTION",
        min_length=1,
    )
    snack_loading_runs_collection: str = Field(
        default="snack_loading_runs",
        validation_alias="MONGODB_SNACK_LOADING_RUNS_COLLECTION",
    )
    snack_machine_layouts_collection: str = Field(
        default="snack_machine_layouts",
        validation_alias="MONGODB_SNACK_MACHINE_LAYOUTS_COLLECTION",
    )
    matrix_sku_catalog_collection: str = Field(
        default="matrix_sku_catalog",
        validation_alias="MONGODB_MATRIX_SKU_CATALOG_COLLECTION",
    )
    matrix_base_margin_collection: str = Field(
        default="matrix_base_margin",
        validation_alias="MONGODB_MATRIX_BASE_MARGIN_COLLECTION",
    )
    sales_monitoring_audit_collection: str = Field(
        default="sales_monitoring_audit",
        validation_alias="MONGODB_SALES_MONITORING_AUDIT_COLLECTION",
    )
    sales_monitoring_worker_status_collection: str = Field(
        default="sales_monitoring_worker_status",
        validation_alias="MONGODB_SALES_MONITORING_WORKER_STATUS_COLLECTION",
    )
    sales_monitoring_status_board_collection: str = Field(
        default="sales_monitoring_status_board",
        validation_alias="MONGODB_SALES_MONITORING_STATUS_BOARD_COLLECTION",
        min_length=1,
    )
    admin_nav_structure_collection: str = Field(
        default="admin_nav_structure",
        validation_alias="MONGODB_ADMIN_NAV_STRUCTURE_COLLECTION",
        min_length=1,
    )
    daily_sales_demand_worker_status_collection: str = Field(
        default="daily_sales_demand_worker_status",
        validation_alias="MONGODB_DAILY_SALES_DEMAND_WORKER_STATUS_COLLECTION",
    )
    machine_pnl_month_worker_status_collection: str = Field(
        default="machine_pnl_month_worker_status",
        validation_alias="MONGODB_MACHINE_PNL_MONTH_WORKER_STATUS_COLLECTION",
    )
    sales_sheet_export_cursor_collection: str = Field(
        default="sales_sheet_export_cursors",
        validation_alias="MONGODB_SALES_SHEET_EXPORT_CURSOR_COLLECTION",
    )
    kitshop_sales_backlog_collection: str = Field(
        default="kitshop_sales_backlog",
        validation_alias="MONGODB_KITSHOP_SALES_BACKLOG_COLLECTION",
        min_length=1,
    )
    kitshop_sales_ingest_cursors_collection: str = Field(
        default="kitshop_sales_ingest_cursors",
        validation_alias="MONGODB_KITSHOP_SALES_INGEST_CURSORS_COLLECTION",
        min_length=1,
    )
    kitshop_sale_receipts_collection: str = Field(
        default="kitshop_sale_receipts",
        validation_alias="MONGODB_KITSHOP_SALE_RECEIPTS_COLLECTION",
        min_length=1,
    )
    kitshop_reference_snapshots_collection: str = Field(
        default="kitshop_reference_snapshots",
        validation_alias="MONGODB_KITSHOP_REFERENCE_SNAPSHOTS_COLLECTION",
        min_length=1,
    )
    form_workflow_session_ttl_seconds: int | None = Field(
        default=None,
        validation_alias="FORM_WORKFLOW_SESSION_TTL_SECONDS",
        gt=0,
    )
    outbox_max_attempts: int = Field(
        default=5,
        validation_alias="OUTBOX_MAX_ATTEMPTS",
    )
    outbox_poll_interval_seconds: float = Field(
        default=1.0,
        validation_alias="OUTBOX_POLL_INTERVAL_SECONDS",
    )
    server_selection_timeout_ms: int = Field(
        default=MONGODB_HEALTHCHECK_TIMEOUT_MS,
        validation_alias="MONGODB_SERVER_SELECTION_TIMEOUT_MS",
        gt=0,
        le=MONGODB_HEALTHCHECK_TIMEOUT_MS,
    )
    connect_timeout_ms: int = Field(
        default=MONGODB_HEALTHCHECK_TIMEOUT_MS,
        validation_alias="MONGODB_CONNECT_TIMEOUT_MS",
        gt=0,
        le=MONGODB_HEALTHCHECK_TIMEOUT_MS,
    )
    socket_timeout_ms: int = Field(
        default=30_000,
        validation_alias="MONGODB_SOCKET_TIMEOUT_MS",
        gt=0,
    )
    max_pool_size: int = Field(
        default=20,
        validation_alias="MONGODB_MAX_POOL_SIZE",
        gt=0,
    )

    @field_validator("snack_machine_layouts_collection")
    @classmethod
    def validate_snack_machine_layouts_collection(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MONGODB_SNACK_MACHINE_LAYOUTS_COLLECTION must not be empty")
        return normalized

    @field_validator("matrix_sku_catalog_collection")
    @classmethod
    def validate_matrix_sku_catalog_collection(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MONGODB_MATRIX_SKU_CATALOG_COLLECTION must not be empty")
        return normalized

    @field_validator("matrix_base_margin_collection")
    @classmethod
    def validate_matrix_base_margin_collection(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MONGODB_MATRIX_BASE_MARGIN_COLLECTION must not be empty")
        return normalized

    @beartype
    def client_driver_kwargs(self) -> dict[str, int]:
        return {
            "serverSelectionTimeoutMS": self.server_selection_timeout_ms,
            "connectTimeoutMS": self.connect_timeout_ms,
            "socketTimeoutMS": self.socket_timeout_ms,
            "maxPoolSize": self.max_pool_size,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.uri and self.uri.strip())
