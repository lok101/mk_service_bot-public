from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher
from beartype import beartype
from fastapi import FastAPI

from src.application.micromarket_loading import ApplyMicromarketSaleToStock
from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.product_identity import SyncProcurementMirror
from src.application.product_identity.ports import ProcurementMirrorStore
from src.config.settings import Settings
from src.infrastructure.alerting.worker_liveness_watchdog import WorkerLivenessWatchdog
from src.infrastructure.composition.bundles import (
    AppConfig,
    FormsBundle,
    MachineOpsBundle,
    OutboxBundle,
    PersistenceBundle,
    PhotoPipelineBundle,
    ReferenceDataBundle,
    SettlementBundle,
    TechnicianWarehouseBundle,
    TelegramBundle,
)
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.composition.wiring.register_outbox_handlers import OutboxProcess
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.moysklad.client import MoySkladClient
from src.infrastructure.product_identity.procurement_mirror_worker import (
    ProductProcurementMirrorSyncWorker,
)
from src.interfaces.telegram.contracts import TelegramDialogBackgroundFactory
from src.interfaces.telegram.form_workflow_notifier import TelegramFormWorkflowNotifier

_APP_CONTAINER: AppContainer | None = None


@beartype
@dataclass
class AppContainer:
    """Composition root: single process (Telegram + FastAPI + outbox worker).

    See docs/operational-assumptions.md.
    """

    config: AppConfig
    persistence: PersistenceBundle
    machine_ops: MachineOpsBundle
    forms: FormsBundle
    outbox: OutboxBundle
    photos: PhotoPipelineBundle
    settlement: SettlementBundle
    reference_data: ReferenceDataBundle
    technician_warehouse: TechnicianWarehouseBundle
    telegram: TelegramBundle
    # LOK-160: call apply_micromarket_sale_to_stock.execute(...) after persist
    # shop sale with machine_code from ShopName.
    apply_micromarket_sale_to_stock: ApplyMicromarketSaleToStock | None = None
    _moysklad_client: MoySkladClient | None = field(default=None, repr=False)
    kitshop_client: KitShopHttpClient | None = None
    micromarket_planogram_store: MicromarketPlanogramStore | None = None
    shop_list_publish_journal: ShopListPublishJournal | None = None
    shop_list_baseline_store: ShopListLastSucceededSnapshotStore | None = None
    procurement_mirror_worker: ProductProcurementMirrorSyncWorker | None = None
    procurement_mirror_store: ProcurementMirrorStore | None = None
    procurement_sync: SyncProcurementMirror | None = None
    worker_liveness_watchdog: WorkerLivenessWatchdog | None = None
    _procurement_mirror_http_close: Callable[[], None] | None = field(
        default=None,
        repr=False,
    )
    _runtime: ProcessRuntime = field(init=False, repr=False)

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> AppContainer:
        from src.infrastructure.composition.wiring.assemble import assemble_app_container

        return assemble_app_container(settings)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_runtime",
            ProcessRuntime(
                config=self.config,
                persistence=self.persistence,
                machine_ops=self.machine_ops,
                forms=self.forms,
                outbox=self.outbox,
                photos=self.photos,
                settlement=self.settlement,
                reference_data=self.reference_data,
                technician_warehouse=self.technician_warehouse,
                telegram=self.telegram,
                _moysklad_client=self._moysklad_client,
                kitshop_client=self.kitshop_client,
                micromarket_planogram_store=self.micromarket_planogram_store,
                shop_list_publish_journal=self.shop_list_publish_journal,
                shop_list_baseline_store=self.shop_list_baseline_store,
                procurement_mirror_worker=self.procurement_mirror_worker,
                procurement_mirror_store=self.procurement_mirror_store,
                procurement_sync=self.procurement_sync,
                worker_liveness_watchdog=self.worker_liveness_watchdog,
                _procurement_mirror_http_close=self._procurement_mirror_http_close,
            ),
        )

    @beartype
    async def run(self) -> None:
        await self._runtime.run()

    @property
    @beartype
    def api_app(self) -> FastAPI:
        return self._runtime.api_app

    @property
    @beartype
    def loading_photos_telegram_registered(self) -> bool:
        return self._runtime.loading_photos_telegram_registered

    @beartype
    def request_shutdown(self) -> None:
        self._runtime.request_shutdown()

    @beartype
    async def aclose_moysklad(self) -> None:
        await self._runtime.aclose_moysklad()
        self._moysklad_client = self._runtime._moysklad_client

    @beartype
    def close(self) -> None:
        if self.persistence.mongo_client is not None:
            self.persistence.mongo_client.close()
        if self.persistence.redis_client is not None:
            self.persistence.redis_client.close()

    @beartype
    def warm_up_reference_data(self) -> None:
        self._runtime.warm_up_reference_data()

    @beartype
    def register_telegram_form_workflow(
        self,
        bot: Bot,
        dialog_bg_factory: TelegramDialogBackgroundFactory,
        *,
        process: OutboxProcess = "ingress",
    ) -> TelegramFormWorkflowNotifier:
        return self._runtime.register_telegram_form_workflow(
            bot,
            dialog_bg_factory,
            process=process,
        )

    @beartype
    def register_telegram_loading_photos(
        self,
        bot: Bot,
        *,
        process: OutboxProcess = "ingress",
    ) -> None:
        self._runtime.register_telegram_loading_photos(bot, process=process)

    @beartype
    def setup_telegram_bot(
        self,
        *,
        process: OutboxProcess = "ingress",
    ) -> tuple[Bot, Dispatcher]:
        return self._runtime.setup_telegram_bot(process=process)


@beartype
def build_app_container(settings: Settings | None = None) -> AppContainer:
    return AppContainer.from_settings(settings)


@beartype
def get_app_container() -> AppContainer:
    global _APP_CONTAINER

    if _APP_CONTAINER is None:
        _APP_CONTAINER = build_app_container()

    return _APP_CONTAINER


@beartype
def reset_app_container() -> None:
    global _APP_CONTAINER

    _APP_CONTAINER = None
