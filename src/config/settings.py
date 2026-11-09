from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from beartype import beartype
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE
from src.config.daily_sales_demand import DailySalesDemandSettings
from src.config.domain_product_identity import DomainProductIdentitySettings
from src.config.effects_worker import EffectsWorkerSettings
from src.config.event_reminders import EventRemindersSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.http_limits import HttpLimitsSettings
from src.config.kitshop import KitShopSettings
from src.config.kitvending import KitVendingSettings
from src.config.location_roster import LocationRosterSettings
from src.config.machine_pnl import MachinePnlSettings
from src.config.machine_pnl_month import MachinePnlMonthSettings
from src.config.master_data import MasterDataSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.micromarket_loading import MicromarketLoadingSettings
from src.config.micromarket_pricing import MicromarketPricingSettings
from src.config.micromarket_supply_order_category import (
    MicromarketSupplyOrderCategorySettings,
)
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.object_storage import ObjectStorageSettings
from src.config.product_catalog_ms import ProductCatalogMsSettings
from src.config.product_procurement_mirror import ProductProcurementMirrorSettings
from src.config.redis import RedisSettings
from src.config.reference_data import ReferenceDataSettings
from src.config.sales_monitoring import SalesMonitoringSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.service_rules import ServiceRulesSettings
from src.config.service_visits import ServiceVisitsSettings
from src.config.settlement import SettlementSettings
from src.config.settlement_analysis import SettlementAnalysisSettings
from src.config.snack_loading import SnackLoadingSettings
from src.config.technician_warehouse import TechnicianWarehouseSettings
from src.config.telegram import TelegramSettings
from src.config.visit_photo_grouping import VisitPhotoGroupingSettings
from src.config.visit_photo_review import VisitPhotoReviewSettings
from src.config.worker_liveness import WorkerLivenessSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "prod", "test"] = Field(
        default="dev",
        validation_alias="ENVIRONMENT",
    )
    api_host: str = Field(default="127.0.0.1", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    api_log_level: str = Field(default="info", validation_alias="API_LOG_LEVEL")

    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    http_limits: HttpLimitsSettings = Field(default_factory=HttpLimitsSettings)
    google_forms: GoogleFormsSettings = Field(default_factory=GoogleFormsSettings)
    google_sheets: GoogleSheetsSettings = Field(default_factory=GoogleSheetsSettings)
    moysklad: MoySkladSettings = Field(default_factory=MoySkladSettings)
    product_catalog_ms: ProductCatalogMsSettings = Field(
        default_factory=ProductCatalogMsSettings,
    )
    product_procurement_mirror: ProductProcurementMirrorSettings = Field(
        default_factory=ProductProcurementMirrorSettings,
    )
    mongodb: MongoSettings = Field(default_factory=MongoSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    service_calendar: ServiceCalendarSettings = Field(
        default_factory=ServiceCalendarSettings,
    )
    service_rules: ServiceRulesSettings = Field(default_factory=ServiceRulesSettings)
    object_storage: ObjectStorageSettings = Field(default_factory=ObjectStorageSettings)
    kitvending: KitVendingSettings = Field(default_factory=KitVendingSettings)
    kitshop: KitShopSettings = Field(default_factory=KitShopSettings)
    settlement: SettlementSettings = Field(default_factory=SettlementSettings)
    reference_data: ReferenceDataSettings = Field(default_factory=ReferenceDataSettings)
    matrix_automation: MatrixAutomationSettings = Field(
        default_factory=MatrixAutomationSettings,
    )
    technician_warehouse: TechnicianWarehouseSettings = Field(
        default_factory=TechnicianWarehouseSettings,
    )
    snack_loading: SnackLoadingSettings = Field(default_factory=SnackLoadingSettings)
    micromarket_loading: MicromarketLoadingSettings = Field(
        default_factory=MicromarketLoadingSettings,
    )
    micromarket_pricing: MicromarketPricingSettings = Field(
        default_factory=MicromarketPricingSettings,
    )
    micromarket_supply_order_category: MicromarketSupplyOrderCategorySettings = Field(
        default_factory=MicromarketSupplyOrderCategorySettings,
    )
    sales_monitoring: SalesMonitoringSettings = Field(
        default_factory=SalesMonitoringSettings,
    )
    machine_pnl: MachinePnlSettings = Field(default_factory=MachinePnlSettings)
    machine_pnl_month: MachinePnlMonthSettings = Field(
        default_factory=MachinePnlMonthSettings,
    )
    event_reminders: EventRemindersSettings = Field(
        default_factory=EventRemindersSettings,
    )
    daily_sales_demand: DailySalesDemandSettings = Field(
        default_factory=DailySalesDemandSettings,
    )
    service_visits: ServiceVisitsSettings = Field(
        default_factory=ServiceVisitsSettings,
    )
    location_roster: LocationRosterSettings = Field(default_factory=LocationRosterSettings)
    master_data: MasterDataSettings = Field(default_factory=MasterDataSettings)
    settlement_analysis: SettlementAnalysisSettings = Field(
        default_factory=SettlementAnalysisSettings,
    )
    visit_photo_review: VisitPhotoReviewSettings = Field(
        default_factory=VisitPhotoReviewSettings,
    )
    domain_product_identity: DomainProductIdentitySettings = Field(
        default_factory=DomainProductIdentitySettings,
    )
    visit_photo_grouping: VisitPhotoGroupingSettings = Field(
        default_factory=VisitPhotoGroupingSettings,
    )
    effects_worker: EffectsWorkerSettings = Field(
        default_factory=EffectsWorkerSettings,
    )
    worker_liveness: WorkerLivenessSettings = Field(
        default_factory=WorkerLivenessSettings,
    )
    outbox_readiness_max_failed: int = Field(
        default=0,
        validation_alias="OUTBOX_READINESS_MAX_FAILED",
        ge=0,
    )

    @model_validator(mode="after")
    def reject_admin_stub_in_prod_or_with_webhook(self) -> Settings:
        stub_on = (
            self.location_roster.dev_stub_login_enabled
            or self.master_data.dev_stub_login_enabled
            or self.settlement_analysis.dev_stub_login_enabled
            or self.visit_photo_review.dev_stub_login_enabled
        )
        if not stub_on:
            return self
        if self.is_production:
            raise ValueError(
                "ADMIN_DEV_STUB_LOGIN_ENABLED cannot be true when ENVIRONMENT=prod",
            )
        if self.telegram.webhook_public_host.strip():
            raise ValueError(
                "ADMIN_DEV_STUB_LOGIN_ENABLED cannot be true when TELEGRAM_WEBHOOK_IP is set",
            )
        return self

    @model_validator(mode="after")
    def require_mirror_when_master_data_export_enabled(self) -> Settings:
        if not self.master_data.sheets_export_enabled:
            return self
        md = self.master_data
        if (
            not md.mirror_spreadsheet_id.strip()
            or md.mirror_locations_sheet_id is None
            or md.mirror_machines_sheet_id is None
        ):
            raise ValueError(
                "MASTER_DATA_SHEETS_EXPORT_ENABLED requires "
                "MASTER_DATA_MIRROR_SPREADSHEET_ID, "
                "MASTER_DATA_MIRROR_LOCATIONS_SHEET_ID, and "
                "MASTER_DATA_MIRROR_MACHINES_SHEET_ID",
            )
        return self

    @model_validator(mode="after")
    def require_layout_master_dependencies(self) -> Settings:
        errors = layout_master_dependency_errors(
            layout_master_enabled=self.matrix_automation.layout_master_enabled,
            master_data_enabled=self.master_data.enabled,
            mongodb_configured=self.mongodb.is_configured,
        )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def require_sku_catalog_master_dependencies(self) -> Settings:
        errors = sku_catalog_master_dependency_errors(
            sku_catalog_master_enabled=self.matrix_automation.sku_catalog_master_enabled,
            master_data_enabled=self.master_data.enabled,
            mongodb_configured=self.mongodb.is_configured,
            folder_ids=self.matrix_automation.sku_catalog_ms_product_folder_ids,
        )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def require_micromarket_loading_execute_dependencies(self) -> Settings:
        if not self.micromarket_loading.execute_enabled:
            return self
        missing = self.micromarket_loading.require_execute_dependencies()
        if self.telegram.alert_chat_id is None:
            missing.append("TELEGRAM_ALERT_CHAT_ID")
        if missing:
            raise ValueError(
                "Micromarket loading execute settings incomplete: " + ", ".join(missing),
            )
        return self

    @property
    def is_dev(self) -> bool:
        return self.environment == "dev"

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"


@beartype
def layout_master_dependency_errors(
    layout_master_enabled: bool,
    master_data_enabled: bool,
    mongodb_configured: bool,
) -> list[str]:
    if not layout_master_enabled:
        return []
    errors: list[str] = []
    if not master_data_enabled:
        errors.append(
            "MASTER_DATA_ENABLED must be true when MATRIX_LAYOUT_MASTER_ENABLED=true",
        )
    if not mongodb_configured:
        errors.append("MONGODB_URI must be set when MATRIX_LAYOUT_MASTER_ENABLED=true")
    return errors


@beartype
def sku_catalog_master_dependency_errors(
    sku_catalog_master_enabled: bool,
    master_data_enabled: bool,
    mongodb_configured: bool,
    folder_ids: tuple[UUID, ...] = (),
) -> list[str]:
    if not sku_catalog_master_enabled:
        return []
    errors: list[str] = []
    if not master_data_enabled:
        errors.append(
            "MASTER_DATA_ENABLED must be true when MATRIX_SKU_CATALOG_MASTER_ENABLED=true",
        )
    if not mongodb_configured:
        errors.append(
            "MONGODB_URI must be set when MATRIX_SKU_CATALOG_MASTER_ENABLED=true",
        )
    if not folder_ids:
        errors.append(
            "MATRIX_SKU_CATALOG_MS_PRODUCT_FOLDER_IDS must be non-empty "
            "when MATRIX_SKU_CATALOG_MASTER_ENABLED=true",
        )
    return errors


@beartype
def matrix_runtime_dependency_errors(settings: Settings, *, when: str) -> list[str]:
    errors: list[str] = []
    if not settings.moysklad.is_configured:
        errors.append(f"MOYSKLAD_API_TOKEN must be set when {when}")
    store_id = settings.moysklad.main_store_id.strip()
    if not store_id:
        errors.append(f"MOYSKLAD_MAIN_STORE_ID must be set when {when}")
    else:
        try:
            UUID(store_id)
        except ValueError:
            errors.append("MOYSKLAD_MAIN_STORE_ID must be a valid UUID")
    from src.infrastructure.integrations.kitvending.platform_accounts import accounts_file_is_valid

    if not accounts_file_is_valid(settings.kitvending.accounts_path):
        errors.append(
            f"KIT_PLATFORM_ACCOUNTS_PATH must point to a valid accounts file when {when}",
        )
    if not settings.kitvending.api_base_url.strip():
        errors.append(f"KITVENDING_API_BASE_URL must be set when {when}")
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        errors.append(f"BOT_TOKEN must be set when {when}")
    if settings.telegram.alert_chat_id is None:
        errors.append(f"TELEGRAM_ALERT_CHAT_ID must be set when {when}")
    return errors


@beartype
def validate_matrix_seed_settings(settings: Settings) -> None:
    if settings.matrix_automation.worker_enabled:
        raise ValueError(
            "matrix_admin seed is refused when MATRIX_WORKER_ENABLED=true",
        )
    errors: list[str] = []
    matrix = settings.matrix_automation
    if not matrix.google_sheets_spreadsheet_id.strip():
        errors.append("MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID must be set for matrix seed")
    if matrix.product_multipliers_sheet_id is None:
        errors.append("MATRIX_PRODUCT_MULTIPLIERS_SHEET_ID must be set for matrix seed")
    credentials_file = settings.google_sheets.credentials_file.strip()
    if not credentials_file:
        errors.append(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE must be set for matrix seed",
        )
    elif not Path(credentials_file).is_file():
        errors.append(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE must point to an existing file "
            "for matrix seed",
        )
    errors.extend(
        matrix_runtime_dependency_errors(settings, when="matrix seed"),
    )
    if errors:
        raise ValueError("; ".join(errors))


@beartype
def validate_matrix_worker_settings(settings: Settings) -> None:
    """Require MoySklad, Kit accounts and Telegram when the nightly worker is enabled."""
    if not settings.matrix_automation.worker_enabled:
        return
    errors = matrix_runtime_dependency_errors(
        settings,
        when="MATRIX_WORKER_ENABLED=true",
    )
    if errors:
        raise ValueError("; ".join(errors))


@beartype
def validate_micromarket_supply_order_category_settings(settings: Settings) -> None:
    """Always-on: nested UUID settings must be present (fail closed, no feature-flag)."""
    cat = settings.micromarket_supply_order_category
    if cat.shelf_life_days_threshold < 0:
        raise ValueError("MICROMARKET_SUPPLY_SHELF_LIFE_DAYS_THRESHOLD must be >= 0")
    _ = (
        cat.attr_shelf_life_days_id,
        cat.folder_snacks_id,
        cat.folder_ready_meals_id,
    )


@beartype
def validate_product_catalog_ms_settings(settings: Settings) -> None:
    """Call from app assemble/runtime when building AppContainer."""
    pcs = settings.product_catalog_ms
    if not pcs.sync_enabled:
        return
    if not settings.moysklad.is_configured:
        raise ValueError(
            "PRODUCT_CATALOG_MS_SYNC_ENABLED=true requires MOYSKLAD_API_TOKEN",
        )
    if not pcs.product_folder_ids:
        raise ValueError(
            "PRODUCT_CATALOG_MS_SYNC_ENABLED=true requires PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS",
        )


@beartype
def validate_product_procurement_mirror_settings(settings: Settings) -> None:
    """Require MoySklad token, UUID main store and attr UUIDs when mirror is enabled."""
    if not settings.product_procurement_mirror.enabled:
        return
    if not settings.moysklad.is_configured:
        raise ValueError(
            "PRODUCT_PROCUREMENT_MIRROR_ENABLED=true requires MOYSKLAD_API_TOKEN",
        )
    store_id = settings.moysklad.main_store_id.strip()
    if not store_id:
        raise ValueError(
            "PRODUCT_PROCUREMENT_MIRROR_ENABLED=true requires MOYSKLAD_MAIN_STORE_ID",
        )
    try:
        UUID(store_id)
    except ValueError as error:
        raise ValueError("MOYSKLAD_MAIN_STORE_ID must be a valid UUID") from error
    mirror = settings.product_procurement_mirror
    for label, raw in (
        ("MOYSKLAD_ATTR_PACKAGE_QUANTITY_ID", mirror.attr_package_quantity_id),
        ("MOYSKLAD_ATTR_SUPPLIER_PRODUCT_NAME_ID", mirror.attr_supplier_product_name_id),
    ):
        value = raw.strip()
        if not value:
            raise ValueError(
                f"PRODUCT_PROCUREMENT_MIRROR_ENABLED=true requires {label}",
            )
        try:
            UUID(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a valid UUID") from error


@beartype
def validate_sales_monitoring_worker_settings(settings: Settings) -> None:
    """Require Mongo and report/alert Telegram when sales-monitoring worker is enabled."""
    if not settings.sales_monitoring.worker_enabled:
        return
    errors: list[str] = []
    sm = settings.sales_monitoring
    uri = settings.mongodb.uri
    if uri is None or not uri.strip():
        errors.append("MONGODB_URI must be set when SALES_MONITORING_WORKER_ENABLED=true")
    report_token = sm.telegram_bot_token
    if report_token is None or not report_token.get_secret_value().strip():
        errors.append(
            "SALES_MONITORING_TELEGRAM_BOT_TOKEN must be set when "
            "SALES_MONITORING_WORKER_ENABLED=true",
        )
    if sm.telegram_chat_id is None:
        errors.append(
            "SALES_MONITORING_TELEGRAM_CHAT_ID must be set when "
            "SALES_MONITORING_WORKER_ENABLED=true",
        )
    if sm.decline_telegram_chat_id is None:
        errors.append(
            "SALES_MONITORING_DECLINE_TELEGRAM_CHAT_ID must be set when "
            "SALES_MONITORING_WORKER_ENABLED=true",
        )
    if sm.alert_telegram_chat_id is None:
        errors.append(
            "SALES_MONITORING_ALERT_TELEGRAM_CHAT_ID must be set when "
            "SALES_MONITORING_WORKER_ENABLED=true",
        )
    if errors:
        raise ValueError("; ".join(errors))


def _require_uuid_field(value: str, *, env_name: str, when: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return f"{env_name} must be set when {when}"
    try:
        UUID(stripped)
    except ValueError:
        return f"{env_name} must be a valid UUID when {when}"
    return None


@beartype
def validate_daily_sales_demand_worker_settings(settings: Settings) -> None:
    """Require Mongo + MS org/project/agent/channels when daily worker enabled in prod."""
    if not settings.daily_sales_demand.worker_enabled:
        return
    if settings.environment != "prod":
        return
    when = "DAILY_SALES_DEMAND_WORKER_ENABLED=true and ENVIRONMENT=prod"
    errors: list[str] = []
    uri = settings.mongodb.uri
    if uri is None or not uri.strip():
        errors.append(f"MONGODB_URI must be set when {when}")
    if not settings.moysklad.is_configured:
        errors.append(f"MOYSKLAD_API_TOKEN must be set when {when}")
    for env_name, value in (
        ("MOYSKLAD_ORGANIZATION_ID", settings.moysklad.organization_id),
        ("MOYSKLAD_PROJECT_ID", settings.moysklad.project_id),
        ("MOYSKLAD_DEMAND_AGENT_ID", settings.moysklad.demand_agent_id),
        ("MOYSKLAD_SNACK_SALES_CHANNEL_ID", settings.moysklad.snack_sales_channel_id),
    ):
        err = _require_uuid_field(value, env_name=env_name, when=when)
        if err is not None:
            errors.append(err)
    if errors:
        raise ValueError("; ".join(errors))


@beartype
def validate_event_reminders_worker_settings(settings: Settings) -> None:
    """Require Telegram and Sheets when event-reminders worker is enabled (no Mongo)."""
    if not settings.event_reminders.worker_enabled:
        return
    errors: list[str] = []
    er = settings.event_reminders
    report_token = er.telegram_bot_token
    if report_token is None or not report_token.get_secret_value().strip():
        errors.append(
            "EVENT_REMINDERS_TELEGRAM_BOT_TOKEN must be set when "
            "EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if er.telegram_chat_id is None:
        errors.append(
            "EVENT_REMINDERS_TELEGRAM_CHAT_ID must be set when EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if er.alert_telegram_chat_id is None:
        errors.append(
            "EVENT_REMINDERS_ALERT_TELEGRAM_CHAT_ID must be set when "
            "EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if not er.spreadsheet_id.strip():
        errors.append(
            "EVENT_REMINDERS_SPREADSHEET_ID must be set when EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if er.sheet_id is None:
        errors.append(
            "EVENT_REMINDERS_SHEET_ID must be set when EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if not er.hours:
        errors.append(
            "EVENT_REMINDERS_HOURS must be set when EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if not er.lead_days:
        errors.append(
            "EVENT_REMINDERS_LEAD_DAYS must be set when EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if not settings.google_sheets.credentials_file.strip():
        errors.append(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE must be set when "
            "EVENT_REMINDERS_WORKER_ENABLED=true",
        )
    if errors:
        raise ValueError("; ".join(errors))


@beartype
def validate_machine_pnl_month_settings(settings: Settings) -> None:
    if not settings.machine_pnl_month.enabled:
        return
    if not settings.machine_pnl.enabled:
        raise ValueError(
            "MACHINE_PNL_MONTH_ENABLED=true requires MACHINE_PNL_ENABLED=true",
        )


@beartype
def validate_machine_pnl_month_worker_settings(settings: Settings) -> None:
    if not settings.machine_pnl_month.worker_enabled:
        return
    validate_machine_pnl_month_settings(settings)
    month = settings.machine_pnl_month
    errors: list[str] = []
    if month.sheet_spreadsheet_id is None:
        errors.append("MACHINE_PNL_MONTH_SHEET_SPREADSHEET_ID")
    if month.sheet_id is None:
        errors.append("MACHINE_PNL_MONTH_SHEET_ID")
    if not settings.google_sheets.is_locations_directory_configured:
        errors.append("LOCATIONS_DIRECTORY_SPREADSHEET_ID")
        errors.append("LOCATIONS_DIRECTORY_SHEET_ID")
    if not settings.google_sheets.is_technicians_directory_configured:
        errors.append("TECHNICIANS_DIRECTORY_SPREADSHEET_ID")
        errors.append("TECHNICIANS_DIRECTORY_SHEET_ID")
    if errors:
        raise ValueError(
            "MACHINE_PNL_MONTH_WORKER_ENABLED=true requires non-empty: " + ", ".join(errors),
        )
    uri = settings.mongodb.uri
    if uri is None or not uri.strip():
        raise ValueError(
            "MONGODB_URI must be set when MACHINE_PNL_MONTH_WORKER_ENABLED=true",
        )


@beartype
def validate_service_visits_worker_settings(settings: Settings) -> None:
    if not settings.service_visits.worker_enabled:
        return
    uri = settings.mongodb.uri
    if uri is None or not uri.strip():
        raise ValueError(
            "MONGODB_URI must be set when SERVICE_VISITS_WORKER_ENABLED=true",
        )


@beartype
@lru_cache
def get_settings() -> Settings:
    return Settings()


@beartype
def reset_settings() -> None:
    get_settings.cache_clear()
