from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from zoneinfo import ZoneInfo

from aiogram import Bot
from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.application.outbox.handler_ids import (
    DAILY_SALES_DEMAND_HANDLER_ID,
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    MACHINE_PNL_MONTH_HANDLER_ID,
    MACHINE_PNL_PERIOD_HANDLER_ID,
    MICROMARKET_LOADING_MOVE_HANDLER_ID,
    MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID,
    MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
    NO_SALES_INCIDENT_CONTROL_HANDLER_ID,
    PERIOD_RECONCILIATION_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
    SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
    SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
    SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
    TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
    VISIT_FORCE_NOTIFY_HANDLER_ID,
)
from src.application.outbox.no_sales_incident_control import (
    NoSalesControlWriter,
    NoSalesIncidentControlHandler,
)
from src.application.outbox.period_reconciliation_handler import PeriodReconciliationHandler
from src.application.outbox.service_visit_on_maintenance import ServiceVisitOnMaintenanceHandler
from src.application.outbox.technician_warehouse_loading import TechnicianWarehouseLoadingHandler
from src.application.outbox.visit_force_notify import VisitForceNotifyHandler
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_batches.outbox_handler import LoadingPhotosOutboxHandler
from src.application.photo_batches.ports import PhotoBatchStore
from src.application.photo_integrity import LoadingPhotosIntegrityOutboxHandler
from src.application.photo_integrity.duplicate_alert import PhotoIntegrityDuplicateAlerter
from src.application.photo_integrity.process_loading_integrity import (
    ProcessLoadingPhotosIntegrity,
)
from src.application.service_visits import (
    ClearNoSalesIncident,
    CloseServiceVisit,
    MachineSalesQtyBaselineLookup,
    NullMachineSalesQtyBaselineLookup,
)
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.machine_pnl.events import MachineMonthPnlRequested, MachinePeriodPnlRequested
from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.domain.sales_monitoring.control_event import NoSalesIncidentControlRequested
from src.domain.service_visits import ServiceVisitForceNotifyRequested
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)
from src.infrastructure.composition.adapters.vending_machine_weekdays import (
    VendingMachineWeekdaysLookup,
)
from src.infrastructure.composition.factories import build_machine_sales_qty_baseline_lookup
from src.infrastructure.composition.record_duplicate_accountability_adapter import (
    RecordPhotoDuplicateAccountabilityAdapter,
)
from src.infrastructure.composition.wiring.deps import OutboxHandlerDeps
from src.infrastructure.outbox.processor import OutboxHandler, OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.photo_batches.scoped_storage import scoped_photo_storage
from src.infrastructure.visit_photo_grouping import subscribe_visit_photo_grouping
from src.interfaces.telegram.loading_photos_outbox import LoadingPhotosTelegramOutboxHandler
from src.interfaces.telegram.visit_force_notify_telegram import AiogramVisitForceNotifyTelegram


def _baseline_lookup_for_deps(deps: OutboxHandlerDeps) -> MachineSalesQtyBaselineLookup:
    sales = deps.machine_sales_store
    if sales is None:
        return NullMachineSalesQtyBaselineLookup()
    return build_machine_sales_qty_baseline_lookup(
        sales=sales,  # type: ignore[arg-type]
        timezone=deps.sales_baseline_timezone,
        days_for_average=deps.sales_baseline_days_for_average,
        baseline_min_points=deps.sales_baseline_min_points,
        baseline_winsorize_min_points=deps.sales_baseline_winsorize_min_points,
        baseline_winsorize_percent=deps.sales_baseline_winsorize_percent,
    )


@beartype
def subscribe_visit_force_notify(publisher: OutboxDomainEventPublisher) -> None:
    """Enqueue path: sales-monitoring publisher subscribes; effects only registers."""
    publisher.subscribe(ServiceVisitForceNotifyRequested, VISIT_FORCE_NOTIFY_HANDLER_ID)


@beartype
def register_visit_force_notify_handler(
    *,
    processors: OutboxProcessorRegistry,
    bot_token: str,
    ops_chat_id: int,
) -> None:
    """Processor only. Subscribe stays on the sales-monitoring publisher."""
    handler = VisitForceNotifyHandler(
        telegram=AiogramVisitForceNotifyTelegram(bot=Bot(token=bot_token)),
        ops_chat_id=ops_chat_id,
    )
    processors.register(
        VISIT_FORCE_NOTIFY_HANDLER_ID,
        cast(OutboxHandler, handler.process),
    )


OutboxProcess = Literal["ingress", "effects"]


@beartype
def register_loading_photos_telegram_handler(
    *,
    publisher: OutboxDomainEventPublisher,
    processors: OutboxProcessorRegistry,
    photo_batch_store: PhotoBatchStore,
    loading_photos_notifier_ref: LoadingPhotosChatNotifierRef,
    vending_machine_repository: VendingMachineRepository,
    service_timezone: ZoneInfo,
    day_end_hour: int,
    process: OutboxProcess = "ingress",
) -> None:
    loading_photos_telegram_handler = LoadingPhotosTelegramOutboxHandler(
        photo_batch_store=photo_batch_store,
        notifier=loading_photos_notifier_ref,
        vending_machine_repository=vending_machine_repository,
        service_timezone=service_timezone,
        day_end_hour=day_end_hour,
        enabled=True,
    )
    _register_if_owner(
        process=process,
        handler_id=LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
        processors=processors,
        handler=cast(OutboxHandler, loading_photos_telegram_handler.process),
    )
    _subscribe_if(
        process=process,
        owner="ingress",
        publisher=publisher,
        event_type=PhotosSubmitted,
        handler_id=LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    )


_NOT_OWNED_HERE = frozenset(
    {
        SERVICE_VISIT_INCIDENT_HANDLER_ID,
    }
)


@beartype
def _owns_processor(process: OutboxProcess, handler_id: str) -> bool:
    if handler_id in _NOT_OWNED_HERE:
        return False
    if handler_id == NO_SALES_INCIDENT_CONTROL_HANDLER_ID:
        return process == "ingress"
    return process == "effects"


@beartype
def _register_if_owner(
    *,
    process: OutboxProcess,
    handler_id: str,
    processors: OutboxProcessorRegistry,
    handler: OutboxHandler,
) -> None:
    if _owns_processor(process, handler_id):
        processors.register(handler_id, handler)


@beartype
def _subscribe_if(
    *,
    process: OutboxProcess,
    owner: OutboxProcess,
    publisher: OutboxDomainEventPublisher,
    event_type: type[object],
    handler_id: str,
) -> None:
    if process == owner:
        publisher.subscribe(event_type, handler_id)


@beartype
def register_outbox_handlers(
    *,
    publisher: OutboxDomainEventPublisher,
    processors: OutboxProcessorRegistry,
    deps: OutboxHandlerDeps,
    process: OutboxProcess = "ingress",
) -> None:
    technician_warehouse_loading_handler = TechnicianWarehouseLoadingHandler(
        form_submission_store=deps.form_submission_store,
        observe_loading=deps.observe_technician_warehouse_loading,
    )
    _register_if_owner(
        process=process,
        handler_id=TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
        processors=processors,
        handler=cast(OutboxHandler, technician_warehouse_loading_handler.process),
    )
    _subscribe_if(
        process=process,
        owner="ingress",
        publisher=publisher,
        event_type=LoadingSubmitted,
        handler_id=TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
    )

    loading_photos_handler = LoadingPhotosOutboxHandler(
        photo_batch_store=deps.photo_batch_store,
        photo_downloader=deps.photo_downloader_ref,
        photo_storage=deps.photo_storage,
        service_timezone=deps.service_timezone,
        key_prefix=deps.object_storage_key_prefix,
        scoped_storage_factory=scoped_photo_storage,
    )
    _register_if_owner(
        process=process,
        handler_id=LOADING_PHOTOS_HANDLER_ID,
        processors=processors,
        handler=cast(OutboxHandler, loading_photos_handler.process),
    )
    _subscribe_if(
        process=process,
        owner="ingress",
        publisher=publisher,
        event_type=PhotosSubmitted,
        handler_id=LOADING_PHOTOS_HANDLER_ID,
    )

    integrity_alerter = PhotoIntegrityDuplicateAlerter(
        alert_notifier=deps.integrity_alert_notifier_ref,
        vending_machine_repository=deps.vending_machine_repository,
        service_timezone=deps.service_timezone,
    )
    process_integrity = ProcessLoadingPhotosIntegrity(
        hash_index=deps.hash_index,
        finding_store=deps.finding_store,
        accountability=RecordPhotoDuplicateAccountabilityAdapter(
            service=deps.record_duplicate,
        ),
        photo_batch_store=deps.photo_batch_store,
        alerter=integrity_alerter,
    )
    loading_photos_integrity_handler = LoadingPhotosIntegrityOutboxHandler(
        photo_batch_store=deps.photo_batch_store,
        process_integrity=process_integrity,
        enabled=deps.photo_integrity_enabled,
    )
    _register_if_owner(
        process=process,
        handler_id=LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
        processors=processors,
        handler=cast(OutboxHandler, loading_photos_integrity_handler.process),
    )
    _subscribe_if(
        process=process,
        owner="ingress",
        publisher=publisher,
        event_type=PhotosSubmitted,
        handler_id=LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    )

    if deps.include_loading_photos_telegram:
        register_loading_photos_telegram_handler(
            publisher=publisher,
            processors=processors,
            photo_batch_store=deps.photo_batch_store,
            loading_photos_notifier_ref=deps.loading_photos_notifier_ref,
            vending_machine_repository=deps.vending_machine_repository,
            service_timezone=deps.service_timezone,
            day_end_hour=deps.service_day_end_hour,
            process=process,
        )

    if deps.daily_sales_demand_handler is not None:
        # Processor on effects (Remap HTTP owner); daily-sales-demand-worker is enqueue-only.
        _register_if_owner(
            process=process,
            handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, deps.daily_sales_demand_handler.process),
        )

    if deps.close_responsibility_period is not None and deps.post_accountability is not None:
        period_reconciliation_handler = PeriodReconciliationHandler(
            close_period=deps.close_responsibility_period,
            post_accountability=deps.post_accountability,
        )
        _register_if_owner(
            process=process,
            handler_id=PERIOD_RECONCILIATION_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, period_reconciliation_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="ingress",
            publisher=publisher,
            event_type=RevisionCompleted,
            handler_id=PERIOD_RECONCILIATION_HANDLER_ID,
        )

    if deps.machine_pnl_period_handler is not None:
        _register_if_owner(
            process=process,
            handler_id=MACHINE_PNL_PERIOD_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, deps.machine_pnl_period_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="effects",
            publisher=publisher,
            event_type=MachinePeriodPnlRequested,
            handler_id=MACHINE_PNL_PERIOD_HANDLER_ID,
        )

    if deps.machine_pnl_month_handler is not None:
        _register_if_owner(
            process=process,
            handler_id=MACHINE_PNL_MONTH_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, deps.machine_pnl_month_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="effects",
            publisher=publisher,
            event_type=MachineMonthPnlRequested,
            handler_id=MACHINE_PNL_MONTH_HANDLER_ID,
        )

    if deps.settlement_portion_sync_handler is not None:
        _register_if_owner(
            process=process,
            handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, deps.settlement_portion_sync_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="ingress",
            publisher=publisher,
            event_type=SettlementPortionSyncTransfersRequested,
            handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        )

    if deps.settlement_portion_sales_verify_handler is not None:
        _register_if_owner(
            process=process,
            handler_id=SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, deps.settlement_portion_sales_verify_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="effects",
            publisher=publisher,
            event_type=SettlementPortionSalesVerifyRequested,
            handler_id=SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
        )

    if deps.settlement_portion_reconcile_handler is not None:
        _register_if_owner(
            process=process,
            handler_id=SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, deps.settlement_portion_reconcile_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="effects",
            publisher=publisher,
            event_type=SettlementPortionReconcileRequested,
            handler_id=SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
        )

    if deps.service_visit_store is not None:
        visit_store = deps.service_visit_store
        weekdays = VendingMachineWeekdaysLookup(machines=deps.vending_machine_repository)
        maintenance_handler = ServiceVisitOnMaintenanceHandler(
            closer=CloseServiceVisit(store=visit_store),
            weekdays=weekdays,
            timezone=deps.service_timezone,
            day_end_hour=deps.service_day_end_hour,
        )
        _register_if_owner(
            process=process,
            handler_id=SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, maintenance_handler.process),
        )
        _subscribe_if(
            process=process,
            owner="ingress",
            publisher=publisher,
            event_type=MaintenanceCompleted,
            handler_id=SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
        )
        _subscribe_if(
            process=process,
            owner="ingress",
            publisher=publisher,
            event_type=PhotosSubmitted,
            handler_id=SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
        )

        incident_clearer = ClearNoSalesIncident(store=visit_store)
        if process == "effects" and deps.task_notify_enabled:
            if deps.bot_token is None or deps.task_notify_telegram_chat_id is None:
                raise ValueError(
                    "task_notify_enabled requires bot_token and task_notify_telegram_chat_id",
                )
            register_visit_force_notify_handler(
                processors=processors,
                bot_token=deps.bot_token,
                ops_chat_id=deps.task_notify_telegram_chat_id,
            )

        if deps.sales_monitoring_audit_store is not None:
            control_handler = NoSalesIncidentControlHandler(
                audit_store=cast(NoSalesControlWriter, deps.sales_monitoring_audit_store),
                no_sales_clearer=incident_clearer,
            )
            _register_if_owner(
                process=process,
                handler_id=NO_SALES_INCIDENT_CONTROL_HANDLER_ID,
                processors=processors,
                handler=cast(OutboxHandler, control_handler.process),
            )
            _subscribe_if(
                process=process,
                owner="ingress",
                publisher=publisher,
                event_type=NoSalesIncidentControlRequested,
                handler_id=NO_SALES_INCIDENT_CONTROL_HANDLER_ID,
            )

    if process == "ingress":
        subscribe_visit_photo_grouping(
            publisher=publisher,
            enabled=deps.visit_photo_grouping_enabled,
        )

    if deps.micromarket_planogram_store is not None:
        from src.application.micromarket_loading import (
            MicromarketShopListPublishHandler,
            PreflightFailed,
        )
        from src.application.micromarket_loading.publish_job import ShopListMatrixGateway

        configured = deps.micromarket_shop_list_gateway
        gateway: ShopListMatrixGateway
        if configured is None:

            class _MissingShopGateway:
                def sync_snapshot(
                    self,
                    *,
                    machine_code: str,
                    lines: object,
                    snapshot_still_current: object = None,
                    catalog_names: object = (),
                ) -> PreflightFailed:
                    del machine_code, lines, snapshot_still_current, catalog_names
                    return PreflightFailed("Магазин Kit Shop для этого аппарата не найден")

            gateway = _MissingShopGateway()
        else:
            gateway = configured
        shop_list_handler = MicromarketShopListPublishHandler(
            store=deps.micromarket_planogram_store,
            gateway=gateway,
            products=deps.domain_product_store,
            stock_store=deps.micromarket_stock_store,
            event_publisher=publisher,
            journal=deps.shop_list_publish_journal,
            baseline_store=deps.shop_list_baseline_store,
            now_factory=lambda: datetime.now(UTC),
        )
        _register_if_owner(
            process=process,
            handler_id=MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, shop_list_handler.process),
        )
        publisher.subscribe(
            MicromarketShopListPublishRequested,
            MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
        )

    if (
        deps.micromarket_loading_move_command_store is not None
        and deps.micromarket_loading_move_client is not None
    ):
        from src.application.outbox.micromarket_loading_move import (
            MicromarketLoadingMoveOutboxHandler,
        )

        move_handler = MicromarketLoadingMoveOutboxHandler(
            command_store=deps.micromarket_loading_move_command_store,
            move_client=deps.micromarket_loading_move_client,
            clock=lambda: datetime.now(UTC),
        )
        _register_if_owner(
            process=process,
            handler_id=MICROMARKET_LOADING_MOVE_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, move_handler.process),
        )
        publisher.subscribe(
            MicromarketLoadingMoveCommandRequested,
            MICROMARKET_LOADING_MOVE_HANDLER_ID,
        )

    if deps.post_visit_squeeze is not None:
        from src.application.outbox.micromarket_post_visit_squeeze import (
            MicromarketPostVisitSqueezeOutboxHandler,
        )

        squeeze_handler = MicromarketPostVisitSqueezeOutboxHandler(
            squeeze=deps.post_visit_squeeze,
        )
        _register_if_owner(
            process=process,
            handler_id=MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID,
            processors=processors,
            handler=cast(OutboxHandler, squeeze_handler.process),
        )
        publisher.subscribe(
            MicromarketPostVisitSqueezeRequested,
            MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID,
        )
