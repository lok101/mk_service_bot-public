from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast, runtime_checkable

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.webhook.security import IPFilter
from aiogram_dialog import setup_dialogs
from beartype import beartype
from fastapi import FastAPI

from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.outbox.handler_ids import NO_SALES_INCIDENT_CONTROL_HANDLER_ID
from src.application.outbox.ports import OutboxAdminStore
from src.application.product_identity import SyncProcurementMirror
from src.application.product_identity.ports import ProcurementMirrorStore
from src.config.settings import Settings, get_settings
from src.infrastructure.alerting.worker_liveness_watchdog import WorkerLivenessWatchdog
from src.infrastructure.composition.bundles.config import AppConfig
from src.infrastructure.composition.bundles.forms import FormsBundle
from src.infrastructure.composition.bundles.machine_ops import MachineOpsBundle
from src.infrastructure.composition.bundles.outbox import OutboxBundle
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.bundles.photos import PhotoPipelineBundle
from src.infrastructure.composition.bundles.reference_data import ReferenceDataBundle
from src.infrastructure.composition.bundles.settlement import SettlementBundle
from src.infrastructure.composition.bundles.technician_warehouse import TechnicianWarehouseBundle
from src.infrastructure.composition.bundles.telegram import TelegramBundle
from src.infrastructure.composition.factories import (
    attach_location_roster,
    attach_master_data,
    attach_system_users,
    attach_technicians,
    build_domain_product_store,
    build_fsm_storage,
    build_issue_micromarket_inventory_link,
    build_issue_snack_inventory_link,
    build_kit_product_groups_loader,
    build_micromarket_device_stock_store,
    build_micromarket_planogram_store,
    build_snack_inventory_cells_source,
    warm_up_reference_data_provider,
)
from src.infrastructure.composition.factories.integrations import kit_shop_company_id
from src.infrastructure.composition.factories.micromarket_loading import (
    MasterDataMachineKindLookup,
)
from src.infrastructure.composition.readiness import (
    ReadinessProbe,
    resolve_reference_data_readiness,
)
from src.infrastructure.composition.wiring.register_outbox_handlers import OutboxProcess
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.moysklad.client import MoySkladClient
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.product_identity.procurement_mirror_worker import (
    ProductProcurementMirrorSyncWorker,
)
from src.interfaces.admin import register_admin_routes
from src.interfaces.google_forms.rate_limit import InMemoryWebhookRateLimiter
from src.interfaces.google_forms.webhook import (
    DirectWarehouseChatNotifier,
    GoogleFormsWebhookDeps,
    NoOpDirectWarehouseChatNotifier,
    WebhookPlaceholderBot,
    WebhookTelegramBot,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.bot_menu import register_bot_menu
from src.interfaces.telegram.contracts import TelegramDialogBackgroundFactory
from src.interfaces.telegram.dialog_recovery import register_dialog_recovery_handlers
from src.interfaces.telegram.direct_warehouse_chat_notifier import (
    TelegramDirectWarehouseChatNotifier,
)
from src.interfaces.telegram.form_workflow_notifier import TelegramFormWorkflowNotifier
from src.interfaces.telegram.machines_dialog import (
    MachineListDeps,
    build_machines_dialog,
    build_machines_router,
)
from src.interfaces.telegram.webhook_api import (
    TelegramWebhookDeps,
    drain_telegram_background_tasks,
    register_telegram_webhook_routes,
)

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class _NoSalesPollWorker(Protocol):
    @property
    def poll_interval_seconds(self) -> float: ...

    async def process_batch_for_handler(
        self,
        handler_id: str,
        *,
        limit: int | None = None,
    ) -> int: ...


@beartype
async def run_no_sales_incident_poll(
    *,
    worker: _NoSalesPollWorker,
    shutdown: asyncio.Event,
) -> None:
    """Drain only the ingress handler. Exceptions stay in this task."""
    while not shutdown.is_set():
        try:
            await worker.process_batch_for_handler(NO_SALES_INCIDENT_CONTROL_HANDLER_ID)
        except Exception:
            _LOGGER.exception("no_sales_incident_control_poll_failed")
        if shutdown.is_set():
            return
        try:
            await asyncio.wait_for(
                shutdown.wait(),
                timeout=worker.poll_interval_seconds,
            )
        except TimeoutError:
            continue


# Caddy peer on compose bridge / local; not a full XFF whitelist.
_UVICORN_FORWARDED_ALLOW_IPS = "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16,127.0.0.1"


@beartype
def admin_ssr_enabled(settings: Settings) -> bool:
    return (
        settings.location_roster.enabled
        or settings.master_data.enabled
        or settings.master_data.users_enabled
        or settings.master_data.technicians_enabled
        or settings.master_data.companies_enabled
        or settings.settlement_analysis.enabled
        or settings.visit_photo_review.enabled
    )


@beartype
@dataclass
class ProcessRuntime:
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
    _moysklad_client: MoySkladClient | None = field(repr=False, default=None)
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
    _shutdown_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _api_server: uvicorn.Server | None = field(default=None, init=False, repr=False)
    _api_app: FastAPI | None = field(default=None, init=False, repr=False)
    _telegram_bot: Bot | None = field(default=None, init=False, repr=False)
    _telegram_dispatcher: Dispatcher | None = field(default=None, init=False, repr=False)
    _loading_photos_telegram_registered: bool = field(default=False, init=False, repr=False)

    @property
    @beartype
    def telegram_uses_webhook(self) -> bool:
        return bool(self.config.telegram_webhook_public_host.strip())

    @property
    @beartype
    def loading_photos_telegram_registered(self) -> bool:
        return self._loading_photos_telegram_registered

    @beartype
    def _replace_outbox_worker(self, worker: OutboxWorker) -> None:
        object.__setattr__(self.outbox, "worker", worker)

    @beartype
    def request_shutdown(self) -> None:
        self._shutdown_event.set()
        if self._api_server is not None:
            self._api_server.should_exit = True

    @beartype
    async def aclose_moysklad(self) -> None:
        if self._moysklad_client is not None:
            await self._moysklad_client.aclose()
            self._moysklad_client = None

    @beartype
    def _webhook_deps_with_runtime_overrides(self) -> GoogleFormsWebhookDeps:
        deps = self.forms.webhook_deps
        notifier: DirectWarehouseChatNotifier
        if self._telegram_bot is not None:
            notifier = TelegramDirectWarehouseChatNotifier(
                bot=self._telegram_bot,
                telegram_user_resolver=deps.telegram_user_resolver,
            )
        else:
            notifier = NoOpDirectWarehouseChatNotifier()
        return GoogleFormsWebhookDeps(
            accept_revision_form_submission=deps.accept_revision_form_submission,
            accept_technician_warehouse_inventory=deps.accept_technician_warehouse_inventory,
            accept_inventory_form_submission=deps.accept_inventory_form_submission,
            form_workflow_notifier=self.photos.form_workflow_notifier_ref,
            direct_warehouse_chat_notifier=notifier,
            telegram_user_resolver=deps.telegram_user_resolver,
            bot=cast(
                WebhookTelegramBot,
                self._telegram_bot or WebhookPlaceholderBot(),
            ),
            token_field_name=deps.token_field_name,
            webhook_secret=deps.webhook_secret,
            webhook_signature_max_age_seconds=deps.webhook_signature_max_age_seconds,
            webhook_max_body_bytes=deps.webhook_max_body_bytes,
            revision_form_token_secret=deps.revision_form_token_secret,
            inventory_form_token_secret=deps.inventory_form_token_secret,
            technician_warehouse_inventory_form_token_secret=(
                deps.technician_warehouse_inventory_form_token_secret
            ),
            verify_revision_form_token=deps.verify_revision_form_token,
            verify_inventory_form_token=deps.verify_inventory_form_token,
            verify_technician_warehouse_inventory_token=deps.verify_technician_warehouse_inventory_token,
            peek_form_token=deps.peek_form_token,
            accept_snack_inventory=deps.accept_snack_inventory,
            snack_inventory_now_form_token_secret=deps.snack_inventory_now_form_token_secret,
            snack_inventory_as_of_form_token_secret=(deps.snack_inventory_as_of_form_token_secret),
            verify_snack_inventory_form_token=deps.verify_snack_inventory_form_token,
            accept_micromarket_inventory=deps.accept_micromarket_inventory,
            micromarket_inventory_now_form_token_secret=(
                deps.micromarket_inventory_now_form_token_secret
            ),
            micromarket_inventory_as_of_form_token_secret=(
                deps.micromarket_inventory_as_of_form_token_secret
            ),
            verify_micromarket_inventory_form_token=deps.verify_micromarket_inventory_form_token,
            inventory_form_qty_max=deps.inventory_form_qty_max,
        )

    @beartype
    def register_telegram(
        self,
        bot: Bot,
        *,
        process: OutboxProcess = "ingress",
    ) -> None:
        from src.infrastructure.composition import runtime_telegram

        runtime_telegram.register_telegram(self, bot, process=process)

    @property
    @beartype
    def publisher(self) -> OutboxDomainEventPublisher:
        return self.outbox.publisher

    @beartype
    def _build_readiness_probe(self) -> ReadinessProbe:
        settings = get_settings()
        outbox_store = self.outbox.worker.store
        outbox_admin = outbox_store if isinstance(outbox_store, OutboxAdminStore) else None
        source_ids, staleness_seconds = resolve_reference_data_readiness(
            self.reference_data.sync.source_ids,
            product_catalog_ms_sync_enabled=settings.product_catalog_ms.sync_enabled,
            sheets_staleness_seconds=settings.reference_data.staleness_alert_seconds,
            ms_staleness_seconds=settings.product_catalog_ms.staleness_alert_seconds,
        )
        return ReadinessProbe(
            mongo_client=self.persistence.mongo_client,
            redis_client=self.persistence.redis_client,
            outbox_admin=outbox_admin,
            reference_data_store=self.reference_data.store,
            reference_data_source_ids=source_ids,
            reference_data_staleness_seconds=staleness_seconds,
        )

    @beartype
    def warm_up_reference_data(self) -> None:
        settings = get_settings()
        warm_up_reference_data_provider(
            provider=self.reference_data.provider,
            store=self.reference_data.store,
            sync=self.reference_data.sync,
            master_data_users_enabled=settings.master_data.users_enabled,
        )
        attach_location_roster(
            self.reference_data.provider,
            settings,
            roster_store=self.reference_data.roster_store,
            snapshot_store=self.reference_data.store,
            now=datetime.now(UTC),
        )
        attach_master_data(
            self.reference_data.provider,
            stores=self.reference_data.master_data_stores,
            enabled=settings.master_data.enabled,
        )
        attach_system_users(
            self.reference_data.provider,
            store=self.reference_data.system_user_store,
            enabled=settings.master_data.users_enabled,
        )
        attach_technicians(
            self.reference_data.provider,
            store=self.reference_data.technician_store,
            enabled=settings.master_data.technicians_enabled,
        )

    @beartype
    def build_api_app(self) -> FastAPI:
        if self._api_app is not None:
            return self._api_app

        settings = get_settings()

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            from src.application.shared.async_bridge import bind_main_event_loop

            bind_main_event_loop(asyncio.get_running_loop())
            yield
            self._shutdown_event.set()
            await drain_telegram_background_tasks()

        google_forms = settings.google_forms
        rate_limiter: InMemoryWebhookRateLimiter | None = None
        if google_forms.webhook_rate_limit_per_minute > 0:
            rate_limiter = InMemoryWebhookRateLimiter(
                max_requests=google_forms.webhook_rate_limit_per_minute,
                window_seconds=60.0,
            )

        self._api_app = build_google_forms_webhook_app(
            self._webhook_deps_with_runtime_overrides(),
            expose_openapi_docs=not settings.is_production,
            readiness=self._build_readiness_probe(),
            outbox_readiness_max_failed=settings.outbox_readiness_max_failed,
            lifespan=lifespan,
            rate_limiter=rate_limiter,
        )
        from src.infrastructure.composition.factories.admin_http_deps import (
            build_admin_http_deps,
        )

        register_admin_routes(
            self._api_app,
            build_admin_http_deps(self, settings),
            enabled=admin_ssr_enabled(settings),
        )
        self._register_micromarket_inventory_now_field_form(self._api_app, settings)
        self._register_coffee_field_forms(self._api_app, settings)
        self._register_technician_warehouse_inventory_field_form(self._api_app, settings)
        if (
            self.telegram_uses_webhook
            and self._telegram_bot is not None
            and self._telegram_dispatcher is not None
        ):
            register_telegram_webhook_routes(
                self._api_app,
                deps=TelegramWebhookDeps(
                    bot=self._telegram_bot,
                    dispatcher=self._telegram_dispatcher,
                    path=self.config.telegram_webhook_path,
                    secret_token=self.config.telegram_webhook_secret,
                    ip_filter=IPFilter.default(),
                    max_body_bytes=settings.http_limits.telegram_webhook_max_body_bytes,
                ),
            )
        return self._api_app

    @beartype
    def _register_micromarket_inventory_now_field_form(
        self,
        app: FastAPI,
        settings: Settings,
    ) -> None:
        mm = settings.micromarket_loading
        accept = self.forms.webhook_deps.accept_micromarket_inventory
        if not mm.is_micromarket_inventory_now_configured or accept is None:
            return
        assert mm.inventory_form_now_token_secret is not None
        from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
        from src.interfaces.field_forms import (
            MicromarketInventoryNowFieldFormDeps,
            register_micromarket_inventory_now_field_form_routes,
        )
        from src.interfaces.telegram.machines.micromarket_inventory_workspace import (
            resolve_micromarket_inventory_form_pages,
        )

        mongo_client = self.persistence.mongo_client
        planogram_store = build_micromarket_planogram_store(settings, client=mongo_client)
        accept_stock = getattr(accept, "stock_store", None)
        stock_store = (
            accept_stock
            if accept_stock is not None
            else build_micromarket_device_stock_store(settings, client=mongo_client)
        )
        products = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=mongo_client,
        )
        groups_loader = build_kit_product_groups_loader(
            self.kitshop_client,
            snapshot_store=self.settlement.kitshop_reference_snapshot_store,
            kit_company_id=kit_shop_company_id(settings.kitshop),
        )

        def load_pages(machine_code: str) -> tuple[InventoryFormPage, ...]:
            loaded = groups_loader()
            kit_group_names = {group_id: group_name for group_id, group_name in loaded[1]}
            return resolve_micromarket_inventory_form_pages(
                machine_code=machine_code,
                planogram_store=planogram_store,
                stock_store=stock_store,
                products=products,
                kit_group_names=kit_group_names,
            )

        visit_finalized = getattr(accept, "visit_finalized", None)
        register_micromarket_inventory_now_field_form_routes(
            app,
            MicromarketInventoryNowFieldFormDeps(
                now_token_secret=mm.inventory_form_now_token_secret.get_secret_value(),
                qty_max=settings.google_forms.inventory_form_qty_max,
                accept_micromarket_inventory=accept,
                load_pages=load_pages,
                products=products,
                visit_finalized=visit_finalized,
                stock_store=stock_store,
                timezone=settings.service_calendar.zone_info(),
                day_end_hour=settings.service_calendar.service_day_end_hour,
                max_body_bytes=settings.http_limits.admin_max_body_bytes,
            ),
        )

    @beartype
    def _register_coffee_field_forms(
        self,
        app: FastAPI,
        settings: Settings,
    ) -> None:
        base_url = settings.micromarket_loading.field_forms_public_base_url.strip()
        if not base_url:
            return
        google_forms = settings.google_forms
        revision_secret = google_forms.revision_form_token_secret.get_secret_value()
        loading_secret = google_forms.loading_form_token_secret.get_secret_value()
        if not revision_secret or not loading_secret:
            return

        from src.application.form_inventory_policy import (
            COFFEE_LOADING_PROFILE_ID,
            COFFEE_REVISION_PROFILE_ID,
            ensure_coffee_policy_profiles,
        )
        from src.application.form_submissions.accept import (
            AcceptInventoryFormSubmissionService,
            AcceptRevisionFormSubmissionService,
        )
        from src.application.form_submissions.coffee_field_form_accept import (
            AcceptCoffeeLoadingFieldForm,
            AcceptCoffeeRevisionFieldForm,
        )
        from src.application.machine_operations.services import (
            RegisterLoadingFromFormService,
            RegisterRevisionFromFormService,
        )
        from src.infrastructure.composition.factories import (
            build_domain_product_store,
            build_form_inventory_policy_store,
        )
        from src.infrastructure.field_forms import (
            CoffeeDomainIngredientProductCodeResolver,
        )
        from src.interfaces.field_forms import (
            CoffeeFieldFormDeps,
            register_coffee_field_form_routes,
        )

        mongo_client = self.persistence.mongo_client
        products = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=mongo_client,
        )
        policies = build_form_inventory_policy_store(
            settings.mongodb,
            client=mongo_client,
        )
        ensure_coffee_policy_profiles(policies)
        revision_profile = policies.get_profile(COFFEE_REVISION_PROFILE_ID)
        loading_profile = policies.get_profile(COFFEE_LOADING_PROFILE_ID)
        if revision_profile is None or loading_profile is None:
            raise RuntimeError("coffee form inventory policy profiles missing after ensure")
        revision_resolver = CoffeeDomainIngredientProductCodeResolver(
            products=products,
            policies=policies,
            profile_id=COFFEE_REVISION_PROFILE_ID,
        )
        loading_resolver = CoffeeDomainIngredientProductCodeResolver(
            products=products,
            policies=policies,
            profile_id=COFFEE_LOADING_PROFILE_ID,
        )
        submission_store = self.forms.submission_store
        accept_revision = AcceptCoffeeRevisionFieldForm(
            accept_revision=AcceptRevisionFormSubmissionService(
                form_submission_store=submission_store,
                register_revision_from_form=RegisterRevisionFromFormService(
                    executor=self.machine_ops.executor,
                ),
                product_code_resolver=revision_resolver,
                form_token_field_name=google_forms.token_field_name,
                quantity_mode=revision_profile.input_mode,
                allow_empty=revision_profile.allow_empty,
                apply_stock_range=revision_profile.apply_stock_range,
                allow_zero=revision_profile.allow_zero,
            ),
        )
        accept_loading = AcceptCoffeeLoadingFieldForm(
            accept_loading=AcceptInventoryFormSubmissionService(
                form_submission_store=submission_store,
                register_loading_from_form=RegisterLoadingFromFormService(
                    executor=self.machine_ops.executor,
                ),
                product_code_resolver=loading_resolver,
                form_token_field_name=google_forms.token_field_name,
                quantity_mode=loading_profile.input_mode,
                allow_empty=loading_profile.allow_empty,
                apply_stock_range=loading_profile.apply_stock_range,
                allow_zero=loading_profile.allow_zero,
            ),
        )
        register_coffee_field_form_routes(
            app,
            CoffeeFieldFormDeps(
                revision_token_secret=revision_secret,
                loading_token_secret=loading_secret,
                qty_max=google_forms.inventory_form_qty_max,
                accept_revision=accept_revision,
                accept_loading=accept_loading,
                products=products,
                policies=policies,
                token_max_age_hours=google_forms.form_token_ttl_hours,
                max_body_bytes=settings.http_limits.admin_max_body_bytes,
            ),
        )

    def _register_technician_warehouse_inventory_field_form(
        self,
        app: FastAPI,
        settings: Settings,
    ) -> None:
        base_url = settings.micromarket_loading.field_forms_public_base_url.strip()
        if not base_url:
            return
        google_forms = settings.google_forms
        token_secret = (
            google_forms.technician_warehouse_inventory_form_token_secret.get_secret_value()
        )
        if not token_secret:
            return
        if google_forms.technician_warehouse_inventory_form_url.strip():
            return

        from src.application.form_inventory_policy import (
            TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
            ensure_coffee_policy_profiles,
        )
        from src.application.technician_warehouse.accept_inventory import (
            AcceptTechnicianWarehouseInventoryService,
        )
        from src.infrastructure.composition.factories import (
            build_domain_product_store,
            build_form_inventory_policy_store,
        )
        from src.infrastructure.field_forms import CoffeeDomainIngredientProductCodeResolver
        from src.interfaces.field_forms.technician_warehouse_inventory import (
            TechnicianWarehouseInventoryFieldFormDeps,
            register_technician_warehouse_inventory_field_form_routes,
        )

        mongo_client = self.persistence.mongo_client
        products = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=mongo_client,
        )
        policies = build_form_inventory_policy_store(
            settings.mongodb,
            client=mongo_client,
        )
        ensure_coffee_policy_profiles(policies)
        resolver = CoffeeDomainIngredientProductCodeResolver(
            products=products,
            policies=policies,
            profile_id=TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
        )
        accept = AcceptTechnicianWarehouseInventoryService(
            form_submission_store=self.forms.submission_store,
            product_code_resolver=resolver,
            form_token_field_name=google_forms.token_field_name,
            executor=self.technician_warehouse.executor,
            allow_empty=False,
        )
        error_notifier: DirectWarehouseChatNotifier
        if self._telegram_bot is not None:
            error_notifier = TelegramDirectWarehouseChatNotifier(
                bot=self._telegram_bot,
                telegram_user_resolver=self.forms.webhook_deps.telegram_user_resolver,
            )
        else:
            error_notifier = NoOpDirectWarehouseChatNotifier()
        register_technician_warehouse_inventory_field_form_routes(
            app,
            TechnicianWarehouseInventoryFieldFormDeps(
                token_secret=token_secret,
                qty_max=99,
                accept=accept,
                products=products,
                policies=policies,
                token_max_age_hours=google_forms.form_token_ttl_hours,
                max_body_bytes=settings.http_limits.admin_max_body_bytes,
                error_notifier=error_notifier,
            ),
        )

    @property
    @beartype
    def api_app(self) -> FastAPI:
        return self.build_api_app()

    @beartype
    def register_telegram_form_workflow(
        self,
        bot: Bot,
        dialog_bg_factory: TelegramDialogBackgroundFactory,
        *,
        process: OutboxProcess = "ingress",
    ) -> TelegramFormWorkflowNotifier:
        from src.infrastructure.composition import runtime_telegram

        return runtime_telegram.register_telegram_form_workflow(
            self,
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
        from src.infrastructure.composition import runtime_telegram

        runtime_telegram.register_telegram_loading_photos(self, bot, process=process)

    @beartype
    def build_machine_list_deps(self) -> MachineListDeps:
        settings = get_settings()
        mongo_client = self.persistence.mongo_client
        domain_product_store = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=mongo_client,
        )
        issue_link = build_issue_snack_inventory_link(settings, client=mongo_client)
        cells_source = None
        if issue_link is not None:
            cells_source = build_snack_inventory_cells_source(
                settings,
                client=mongo_client,
            )
        mm_issue = build_issue_micromarket_inventory_link(
            settings,
            client=mongo_client,
            products=domain_product_store,
        )
        mm_planogram = None
        mm_stock = None
        kind_lookup = None
        if mm_issue is not None or self.reference_data.master_data_stores is not None:
            mm_planogram = build_micromarket_planogram_store(settings, client=mongo_client)
            mm_stock = build_micromarket_device_stock_store(settings, client=mongo_client)
            if self.reference_data.master_data_stores is not None:
                kind_lookup = MasterDataMachineKindLookup(
                    _machines=self.reference_data.master_data_stores.machines,
                )
        kit_groups_loader = None
        if mm_issue is not None:
            kit_groups_loader = build_kit_product_groups_loader(
                self.kitshop_client,
                snapshot_store=self.settlement.kitshop_reference_snapshot_store,
                kit_company_id=kit_shop_company_id(settings.kitshop),
            )
        return MachineListDeps(
            service_display_timezone=self.machine_ops.repository.service_calendar_timezone,
            service_day_end_hour=settings.service_calendar.service_day_end_hour,
            visit_store=self.telegram.visit_store,
            telegram_user_resolver=self.forms.telegram_user_resolver,
            vending_machine_repository=self.machine_ops.vending_machines,
            machine_operations=self.machine_ops.repository,
            list_available_machines=self.machine_ops.list_available_machines,
            get_service_capabilities=self.machine_ops.get_service_capabilities,
            complete_maintenance=self.machine_ops.complete_maintenance,
            create_loading_form=self.machine_ops.create_loading_form,
            form_workflow_sessions=self.forms.workflow_session_store,
            accept_loading_photos=self.photos.accept_loading_photos,
            loading_photos_min_count=self.photos.accept_loading_photos.loading_photos_min_count,
            loading_photos_max_count=self.photos.accept_loading_photos.loading_photos_max_count,
            maintenance_cooldown_minutes=self.machine_ops.maintenance_cooldown_minutes,
            issue_snack_inventory_link=issue_link,
            snack_inventory_cells=cells_source,
            issue_micromarket_inventory_link=mm_issue,
            micromarket_planogram_store=mm_planogram,
            micromarket_stock_store=mm_stock,
            machine_kind_lookup=kind_lookup,
            loading_photos_profile_lookup=(self.photos.accept_loading_photos.profile_lookup),
            visit_photo_profile_strict=(self.photos.accept_loading_photos.profile_strict),
            domain_product_store=domain_product_store,
            load_kit_product_groups=kit_groups_loader,
        )

    @beartype
    async def run_bot_polling(self, bot: Bot, dispatcher: Dispatcher) -> None:
        await register_bot_menu(bot)
        polling_task = asyncio.create_task(
            dispatcher.start_polling(bot, handle_signals=False),
        )
        try:
            await self._shutdown_event.wait()
        finally:
            if not polling_task.done():
                try:
                    await dispatcher.stop_polling()
                except RuntimeError:
                    polling_task.cancel()
            await polling_task

    @beartype
    async def configure_telegram_webhook(self, bot: Bot) -> None:
        await register_bot_menu(bot)
        settings = get_settings()
        await bot.set_webhook(
            url=settings.telegram.build_webhook_url(),
            secret_token=self.config.telegram_webhook_secret,
            drop_pending_updates=True,
        )

    @beartype
    def setup_telegram_bot(
        self,
        *,
        process: OutboxProcess = "ingress",
    ) -> tuple[Bot, Dispatcher]:
        bot = Bot(token=self.config.bot_token)

        settings = get_settings()
        dispatcher = Dispatcher(storage=build_fsm_storage(settings))
        dispatcher.include_router(
            build_machines_router(
                machine_dialog_deps=self.telegram.machine_dialog_deps,
            ),
        )
        dispatcher.include_router(build_machines_dialog(self.build_machine_list_deps()))
        dialog_bg_factory = setup_dialogs(dispatcher)
        register_dialog_recovery_handlers(dispatcher)
        self.register_telegram_form_workflow(
            bot,
            cast(TelegramDialogBackgroundFactory, dialog_bg_factory),
            process=process,
        )
        self.register_telegram_loading_photos(bot, process=process)
        self.register_telegram(bot, process=process)
        self._telegram_bot = bot
        self._telegram_dispatcher = dispatcher

        return bot, dispatcher

    @beartype
    async def run_api(self) -> None:
        self._api_server = uvicorn.Server(
            uvicorn.Config(
                self.api_app,
                host=self.config.api_host,
                port=self.config.api_port,
                log_level=self.config.api_log_level,
                proxy_headers=True,
                forwarded_allow_ips=_UVICORN_FORWARDED_ALLOW_IPS,
            ),
        )
        await self._api_server.serve()

    @beartype
    async def _run_sales_ingest_until_shutdown(self) -> None:
        worker = self.settlement.sales_ingest_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("kitvending_sales_ingest_failed")

    @beartype
    async def _run_kitshop_sales_ingest_until_shutdown(self) -> None:
        worker = self.settlement.kitshop_sales_ingest_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("kitshop_sales_ingest_failed")

    @beartype
    async def _run_kitshop_reference_snapshot_until_shutdown(self) -> None:
        worker = self.settlement.kitshop_reference_snapshot_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("kitshop_reference_snapshot_worker_failed")

    @beartype
    async def _run_micromarket_loading_alert_until_shutdown(self) -> None:
        worker = self.machine_ops.micromarket_loading_alert_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("micromarket_loading_alert_worker_failed")

    @beartype
    async def _run_micromarket_warehouse_stock_sync_until_shutdown(self) -> None:
        worker = self.machine_ops.micromarket_warehouse_stock_sync_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("micromarket_warehouse_stock_sync_worker_failed")

    @beartype
    async def _run_supply_order_category_facts_sync_until_shutdown(self) -> None:
        worker = self.machine_ops.supply_order_category_facts_sync_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("supply_order_category_facts_sync_worker_failed")

    @beartype
    async def _run_worker_liveness_watchdog_until_shutdown(self) -> None:
        worker = self.worker_liveness_watchdog
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("worker_liveness_watchdog_failed")

    @beartype
    async def _run_reference_data_until_shutdown(self) -> None:
        try:
            await self.reference_data.worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("reference_data_worker_failed")

    @beartype
    async def _run_product_catalog_ms_until_shutdown(self) -> None:
        worker = self.reference_data.product_catalog_ms_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("product_catalog_ms_worker_failed")

    @beartype
    async def _run_procurement_mirror_until_shutdown(self) -> None:
        worker = self.procurement_mirror_worker
        if worker is None:
            return
        try:
            await worker.run(self._shutdown_event)
        except Exception:
            _LOGGER.exception("product_procurement_mirror_worker_failed")

    @beartype
    def _ingress_background_tasks(self) -> list[asyncio.Task[None]]:
        tasks: list[asyncio.Task[None]] = []
        if self.worker_liveness_watchdog is not None:
            tasks.append(
                asyncio.create_task(self._run_worker_liveness_watchdog_until_shutdown()),
            )
        return tasks

    @beartype
    def _effects_background_tasks(self) -> list[asyncio.Task[None]]:
        tasks: list[asyncio.Task[None]] = []
        if self.reference_data.sync.source_ids:
            tasks.append(
                asyncio.create_task(self._run_reference_data_until_shutdown()),
            )
        if self.reference_data.product_catalog_ms_worker is not None:
            tasks.append(
                asyncio.create_task(self._run_product_catalog_ms_until_shutdown()),
            )
        if self.procurement_mirror_worker is not None:
            tasks.append(
                asyncio.create_task(self._run_procurement_mirror_until_shutdown()),
            )
        if self.settlement.sales_ingest_worker is not None:
            tasks.append(asyncio.create_task(self._run_sales_ingest_until_shutdown()))
        if self.settlement.kitshop_sales_ingest_worker is not None:
            tasks.append(
                asyncio.create_task(self._run_kitshop_sales_ingest_until_shutdown()),
            )
        if self.settlement.kitshop_reference_snapshot_worker is not None:
            tasks.append(
                asyncio.create_task(self._run_kitshop_reference_snapshot_until_shutdown()),
            )
        if self.machine_ops.micromarket_loading_alert_worker is not None:
            tasks.append(
                asyncio.create_task(self._run_micromarket_loading_alert_until_shutdown()),
            )
        if self.machine_ops.micromarket_warehouse_stock_sync_worker is not None:
            tasks.append(
                asyncio.create_task(
                    self._run_micromarket_warehouse_stock_sync_until_shutdown(),
                ),
            )
        if self.machine_ops.supply_order_category_facts_sync_worker is not None:
            tasks.append(
                asyncio.create_task(
                    self._run_supply_order_category_facts_sync_until_shutdown(),
                ),
            )
        return tasks

    @beartype
    async def _run_no_sales_poll_until_shutdown(self) -> None:
        await run_no_sales_incident_poll(
            worker=self.outbox.worker,
            shutdown=self._shutdown_event,
        )

    @beartype
    async def run(self) -> None:
        bot: Bot | None = None
        dispatcher: Dispatcher | None = None
        if self.config.bot_token.strip():
            bot, dispatcher = self.setup_telegram_bot()
        worker_tasks = [
            asyncio.create_task(self._run_no_sales_poll_until_shutdown()),
            *self._ingress_background_tasks(),
        ]
        try:
            # Empty BOT_TOKEN: skip_telegram_polling — keep API + outbox alive for e2e/dev.
            if not self.config.bot_token.strip():
                await asyncio.gather(
                    self.run_api(),
                    *worker_tasks,
                )
                return

            if self.telegram_uses_webhook:
                if bot is None:
                    raise RuntimeError("BOT_TOKEN required for Telegram webhook")
                await self.configure_telegram_webhook(bot)
                await asyncio.gather(
                    self.run_api(),
                    *worker_tasks,
                )
                return

            if bot is None or dispatcher is None:
                raise RuntimeError("BOT_TOKEN required for Telegram webhook/polling")
            await asyncio.gather(
                self.run_api(),
                self.run_bot_polling(bot, dispatcher),
                *worker_tasks,
            )
        finally:
            for task in worker_tasks:
                if not task.done():
                    task.cancel()
            if worker_tasks:
                await asyncio.gather(*worker_tasks, return_exceptions=True)
            self._close_kitvending_client()
            self._close_procurement_mirror_http()

    @beartype
    def _close_kitvending_client(self) -> None:
        from src.infrastructure.integrations.kitvending.client import KitVendingHttpClient

        client = self.settlement.kitvending_client
        if isinstance(client, KitVendingHttpClient):
            client.close()

    @beartype
    def _close_procurement_mirror_http(self) -> None:
        closer = self._procurement_mirror_http_close
        if closer is not None:
            closer()
