from __future__ import annotations

from typing import cast

from aiogram import Bot
from beartype import beartype

from src.application.outbox.handler_ids import (
    LOADING_TELEGRAM_HANDLER_ID,
    REVISION_TELEGRAM_HANDLER_ID,
    TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
)
from src.config.settings import get_settings
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    RevisionCompleted,
)
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.composition.adapters.outbox_failure_notifier import (
    build_outbox_failure_notifier,
)
from src.infrastructure.composition.factories.micromarket_loading import (
    MasterDataMachineKindLookup,
)
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    OutboxProcess,
    register_loading_photos_telegram_handler,
)
from src.infrastructure.outbox.event_deserializer import OutboxEventDeserializerAdapter
from src.infrastructure.outbox.processor import OutboxHandler
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.photo_batches.telegram_downloader import AiogramTelegramPhotoDownloader
from src.interfaces.telegram.contracts import TelegramDialogBackgroundFactory
from src.interfaces.telegram.form_workflow_notifier import TelegramFormWorkflowNotifier
from src.interfaces.telegram.form_workflow_outbox import FormWorkflowTelegramOutboxHandler
from src.interfaces.telegram.loading_photos_notifier import (
    KindRoutedLoadingPhotosChatNotifier,
)
from src.interfaces.telegram.photo_integrity_alert_notifier import (
    TelegramPhotoIntegrityAlertNotifier,
)
from src.interfaces.telegram.technician_warehouse_inventory_outbox import (
    TechnicianWarehouseInventoryTelegramHandler,
)


@beartype
def register_telegram(
    runtime: ProcessRuntime,
    bot: Bot,
    *,
    process: OutboxProcess = "ingress",
) -> None:
    if process == "effects":
        handler = TechnicianWarehouseInventoryTelegramHandler(
            telegram_user_resolver=runtime.forms.telegram_user_resolver,
            bot=bot,
        )
        runtime.outbox.processors.register(
            TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
            cast(OutboxHandler, handler.process),
        )
    else:
        runtime.outbox.publisher.subscribe(
            TechnicianWarehouseInventoryCounted,
            TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
        )
    runtime._telegram_bot = bot
    runtime._api_app = None


@beartype
def register_telegram_form_workflow(
    runtime: ProcessRuntime,
    bot: Bot,
    dialog_bg_factory: TelegramDialogBackgroundFactory,
    *,
    process: OutboxProcess = "ingress",
) -> TelegramFormWorkflowNotifier:
    if isinstance(
        runtime.photos.form_workflow_notifier_ref.notifier,
        TelegramFormWorkflowNotifier,
    ):
        return runtime.photos.form_workflow_notifier_ref.notifier

    notifier = TelegramFormWorkflowNotifier(
        bot=bot,
        session_store=runtime.forms.workflow_session_store,
        telegram_user_resolver=runtime.forms.telegram_user_resolver,
        dialog_bg_factory=dialog_bg_factory,
        machine_list_deps=runtime.build_machine_list_deps(),
    )
    runtime.photos.form_workflow_notifier_ref.notifier = notifier
    runtime._api_app = None
    runtime._replace_outbox_worker(
        OutboxWorker(
            store=runtime.outbox.worker.store,
            processors=runtime.outbox.worker.processors,
            poll_interval_seconds=runtime.outbox.worker.poll_interval_seconds,
            batch_size=runtime.outbox.worker.batch_size,
            failure_notifier=build_outbox_failure_notifier(
                get_settings(),
                form_submission_store=runtime.forms.submission_store,
                form_workflow_notifier=notifier,
                event_deserializer=OutboxEventDeserializerAdapter(),
                planogram_store=runtime.micromarket_planogram_store,
                shop_list_publish_journal=runtime.shop_list_publish_journal,
            ),
        ),
    )

    if process == "effects":
        telegram_outbox = FormWorkflowTelegramOutboxHandler(notifier=notifier)
        runtime.outbox.processors.register(
            REVISION_TELEGRAM_HANDLER_ID,
            cast(OutboxHandler, telegram_outbox.process_revision),
        )
        runtime.outbox.processors.register(
            LOADING_TELEGRAM_HANDLER_ID,
            cast(OutboxHandler, telegram_outbox.process_loading),
        )
    else:
        runtime.outbox.publisher.subscribe(RevisionCompleted, REVISION_TELEGRAM_HANDLER_ID)
        runtime.outbox.publisher.subscribe(LoadingSubmitted, LOADING_TELEGRAM_HANDLER_ID)
    return notifier


@beartype
def register_telegram_loading_photos(
    runtime: ProcessRuntime,
    bot: Bot,
    *,
    process: OutboxProcess = "ingress",
) -> None:
    settings = get_settings()
    telegram_settings = settings.telegram

    if not isinstance(runtime.photos.downloader_ref.downloader, AiogramTelegramPhotoDownloader):
        runtime.photos.downloader_ref.downloader = AiogramTelegramPhotoDownloader(bot)

    if telegram_settings.photo_integrity_alerts_enabled and not isinstance(
        runtime.photos.integrity_alert_notifier_ref.notifier,
        TelegramPhotoIntegrityAlertNotifier,
    ):
        alert_chat_id = telegram_settings.photo_integrity_alert_chat_id
        assert alert_chat_id is not None
        runtime.photos.integrity_alert_notifier_ref.notifier = TelegramPhotoIntegrityAlertNotifier(
            bot=bot,
            chat_id=alert_chat_id,
            photo_storage=runtime.photos.storage,
        )

    if not telegram_settings.loading_photos_proxy_enabled:
        return

    if runtime._loading_photos_telegram_registered:
        return

    kind_lookup = MasterDataMachineKindLookup(
        _machines=runtime.reference_data.master_data_stores.machines,
    )
    runtime.photos.loading_photos_notifier_ref.notifier = KindRoutedLoadingPhotosChatNotifier(
        bot=bot,
        kind_lookup=kind_lookup,
        coffee_chat_id=telegram_settings.loading_photos_chat_id,
        micromarket_chat_id=telegram_settings.micromarket_loading_photos_chat_id,
    )
    register_loading_photos_telegram_handler(
        publisher=runtime.outbox.publisher,
        processors=runtime.outbox.processors,
        photo_batch_store=runtime.photos.batch_store,
        loading_photos_notifier_ref=runtime.photos.loading_photos_notifier_ref,
        vending_machine_repository=runtime.machine_ops.vending_machines,
        service_timezone=runtime.machine_ops.service_calendar_timezone,
        day_end_hour=settings.service_calendar.service_day_end_hour,
        process=process,
    )
    runtime._loading_photos_telegram_registered = True
