from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.form_submissions.ports import (
    ExternalSideEffectRegistry,
    FormSubmissionStore,
    TelegramUserResolver,
)
from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import VendingMachineRepository
from src.application.master_data import MasterMachineStore
from src.application.micromarket_loading.move_command import MicromarketLoadingMoveCommandStore
from src.application.micromarket_loading.move_gateway import MicromarketMoveGateway
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.micromarket_loading.post_visit_squeeze import PostVisitSqueeze
from src.application.outbox.daily_sales_demand import DailySalesDemandHandler
from src.application.outbox.machine_pnl_month import MachinePnlMonthHandler
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.application.outbox.settlement_portion_reconcile import (
    SettlementPortionReconcileHandler,
)
from src.application.outbox.settlement_portion_sales_verify import (
    SettlementPortionSalesVerifyHandler,
)
from src.application.outbox.settlement_portion_sync_transfers import (
    SettlementPortionSyncTransfersHandler,
)
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_batches.ports import PhotoBatchStore, PhotoStorage
from src.application.photo_integrity.notifier_ref import PhotoIntegrityAlertNotifierRef
from src.application.photo_integrity.ports import (
    PhotoContentHashIndex,
    PhotoIntegrityFindingStore,
)
from src.application.product_identity.ports import DomainProductStore
from src.application.sales_monitoring.no_sales_control import NoSalesVisitBlockLookup
from src.application.service_visits.ports import ServiceVisitStore
from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.infrastructure.integrations.kitshop.matrix_gateway import KitShopMatrixGateway
from src.infrastructure.visit_photo_grouping import VisitPhotoGroupingOutboxHandler


@dataclass(frozen=True, slots=True)
class OutboxHandlerDeps:
    form_submission_store: FormSubmissionStore
    observe_technician_warehouse_loading: ObserveTechnicianWarehouseLoading
    photo_batch_store: PhotoBatchStore
    photo_storage: PhotoStorage
    photo_downloader_ref: PhotoDownloaderRef
    loading_photos_notifier_ref: LoadingPhotosChatNotifierRef
    integrity_alert_notifier_ref: PhotoIntegrityAlertNotifierRef
    hash_index: PhotoContentHashIndex
    finding_store: PhotoIntegrityFindingStore
    record_duplicate: RecordPhotoDuplicateSuspectedService
    vending_machine_repository: VendingMachineRepository
    service_timezone: ZoneInfo
    object_storage_key_prefix: str
    photo_integrity_enabled: bool
    include_loading_photos_telegram: bool
    machine_sales_store: object | None = None
    coffee_recipe_repo: object | None = None
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository | None = None
    revision_history: object | None = None
    close_responsibility_period: CloseResponsibilityPeriodOnRevision | None = None
    post_accountability: PostPeriodAccountability | None = None
    side_effect_registry: ExternalSideEffectRegistry | None = None
    service_visit_store: ServiceVisitStore | None = None
    master_machine_store: MasterMachineStore | None = None
    service_day_end_hour: int = 6
    no_sales_min_baseline_qty: Decimal = Decimal("0")
    sales_baseline_timezone: ZoneInfo = ZoneInfo("Asia/Yekaterinburg")
    sales_baseline_days_for_average: int = 28
    sales_baseline_min_points: int = 4
    sales_baseline_winsorize_min_points: int = 8
    sales_baseline_winsorize_percent: int = 10
    machine_pnl_period_handler: MachinePnlPeriodHandler | None = None
    machine_pnl_month_handler: MachinePnlMonthHandler | None = None
    daily_sales_demand_handler: DailySalesDemandHandler | None = None
    settlement_portion_sync_handler: SettlementPortionSyncTransfersHandler | None = None
    settlement_portion_sales_verify_handler: SettlementPortionSalesVerifyHandler | None = None
    settlement_portion_reconcile_handler: SettlementPortionReconcileHandler | None = None
    visit_photo_grouping_enabled: bool = False
    visit_photo_grouping_handler: VisitPhotoGroupingOutboxHandler | None = None
    micromarket_planogram_store: MicromarketPlanogramStore | None = None
    micromarket_stock_store: MicromarketDeviceStockStore | None = None
    shop_list_publish_journal: ShopListPublishJournal | None = None
    shop_list_baseline_store: ShopListLastSucceededSnapshotStore | None = None
    micromarket_shop_list_gateway: KitShopMatrixGateway | None = None
    domain_product_store: DomainProductStore | None = None
    sales_monitoring_audit_store: NoSalesVisitBlockLookup | None = None
    telegram_user_resolver: TelegramUserResolver | None = None
    bot_token: str | None = None
    task_notify_enabled: bool = False
    task_notify_telegram_chat_id: int | None = None
    micromarket_loading_move_command_store: MicromarketLoadingMoveCommandStore | None = None
    micromarket_loading_move_client: MicromarketMoveGateway | None = None
    post_visit_squeeze: PostVisitSqueeze | None = None
