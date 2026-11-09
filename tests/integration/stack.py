from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, create_autospec

from aiogram import Bot
from beartype import beartype
from fastapi.testclient import TestClient
from pymongo.database import Database
from tests.application.product_identity.fakes import FakeDomainProductStore
from tests.integration.settlement_period_close import (
    build_integration_close_responsibility_period,
)
from tests.interfaces._warehouse_webhook_dep_fields import NoOpDirectWarehouseChatNotifier

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.application.form_submissions.ports import (
    ExternalSideEffectRegistry,
    TelegramUserResolver,
)
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.inventory_reconciliation import RefreshPendingPeriodReconciliations
from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import (
    RegisterLoadingFromFormService,
    RegisterLoadingPhotosService,
    RegisterRevisionFromFormService,
)
from src.application.outbox.handler_ids import (
    TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
)
from src.application.photo_batches.accept import AcceptLoadingPhotosService
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_integrity import PhotoIntegrityAlertNotifierRef
from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.technician_accountability.executor import TechnicianAccountabilityExecutor
from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.finalize_reconciliation import (
    FinalizeTechnicianReconciliation,
)
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse.accept_inventory import (
    AcceptTechnicianWarehouseInventoryService,
)
from src.application.technician_warehouse.delta import TechnicianWarehouseDeltaService
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.application.technician_warehouse.ports import (
    ExternalWarehouseMove,
    ReadMovesResult,
    TechnicianWarehouseDeltaPort,
    TechnicianWarehouseRepository,
    TechnicianWarehouseTransferReader,
)
from src.config.service_rules import ServiceRulesSettings
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.form_tokens import (
    peek_form_token,
    verify_inventory_form_token,
    verify_revision_form_token,
    verify_technician_warehouse_inventory_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.composition.adapters.period_party_names import (
    VendingMachinePeriodPartyNamesLookup,
)
from src.infrastructure.composition.adapters.warehouse_session_finalize import (
    WarehouseSessionFinalizeAdapter,
)
from src.infrastructure.composition.refresh_pending_with_accountability import (
    RefreshPendingWithAccountability,
)
from src.infrastructure.composition.wiring.deps import OutboxHandlerDeps
from src.infrastructure.composition.wiring.register_outbox_handlers import register_outbox_handlers
from src.infrastructure.integrations.moysklad.product_spec_resolver import (
    MappingProductSpecByCodeResolver,
)
from src.infrastructure.integrations.moysklad.warehouse_move_quantity import (
    MoySkladCatalogBaseQuantityResolver,
)
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.machine_revision_history import EventStoreMachineRevisionHistoryReader
from src.infrastructure.memory import EventSourcedMachineOperationsRepository
from src.infrastructure.memory_side_effects import InMemoryExternalSideEffectRegistry
from src.infrastructure.mongodb import MongoEventStore
from src.infrastructure.mongodb.coffee_recipes import MongoCoffeeRecipeRepository
from src.infrastructure.mongodb.form_submissions import MongoFormSubmissionStore
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.mongodb.photo_batches import MongoPhotoBatchStore
from src.infrastructure.mongodb.photo_content_hashes import MongoPhotoContentHashIndex
from src.infrastructure.mongodb.photo_integrity_findings import MongoPhotoIntegrityFindingStore
from src.infrastructure.mongodb.reconciliation_drafts import MongoReconciliationDraftStore
from src.infrastructure.mongodb.reconciliation_residual_documents import (
    MongoReconciliationResidualDocumentRepository,
)
from src.infrastructure.mongodb.responsibility_period_reconciliations import (
    MongoPeriodReconciliationRepository,
)
from src.infrastructure.mongodb.technician_settlement import (
    MongoTechnicianSettlementEventStore,
    MongoTechnicianSettlementRepository,
)
from src.infrastructure.mongodb.technician_warehouse import (
    MongoTechnicianWarehouseEventStore,
    MongoTechnicianWarehouseRepository,
)
from src.infrastructure.outbox.mongo import MongoOutboxStore
from src.infrastructure.outbox.processor import OutboxHandler, OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.photo_batches.stubs import (
    InMemoryPhotoStorage,
    StubTelegramPhotoDownloader,
)
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
    InMemoryTechnicianAccountabilityRepository,
)
from src.infrastructure.testing import OTHER_TECHNICIAN_ID, TEST_TECHNICIAN_ID
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    WebhookPlaceholderBot,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier
from src.interfaces.telegram.photo_integrity_alert_notifier import NoOpPhotoIntegrityAlertNotifier
from src.interfaces.telegram.technician_warehouse_inventory_outbox import (
    TechnicianWarehouseInventoryTelegramHandler,
)

WEBHOOK_SIGNATURE_MAX_AGE_SECONDS = 300

WEBHOOK_SECRET = "integration-webhook-secret"
FORM_TOKEN_SECRET = "integration-form-token-secret"
INVENTORY_FORM_TOKEN_SECRET = "integration-inventory-secret"
WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET = "integration-warehouse-inventory-secret"
FORM_TOKEN_FIELD_NAME = "Код заявки."


@beartype
@dataclass(frozen=True, slots=True)
class CatalogProductCodeResolver:
    _mapping: dict[str, str]
    _aliases: dict[str, str] = field(default_factory=dict)
    pack_size: Decimal = Decimal("20")
    unit: ProductUnit = ProductUnit.GRAM

    @beartype
    def resolve_by_name(self, product_name: str) -> ProductSpec:
        return self._resolve(product_name)

    @beartype
    def try_resolve_by_code(self, product_code: str) -> ProductSpec | None:
        if not product_code.strip():
            raise ValueError("Product code must not be empty")
        domain_code = self._aliases.get(product_code, product_code)
        for name, code in self._mapping.items():
            if code == domain_code:
                return self._spec(code=code, name=name)
        return None

    @beartype
    def resolve_by_code(self, product_code: str) -> ProductSpec:
        spec = self.try_resolve_by_code(product_code)
        if spec is None:
            raise ValueError(f"Product code not found: {product_code!r}")
        return spec

    @beartype
    def _resolve(self, product_name: str) -> ProductSpec:
        normalized = product_name.strip()
        try:
            code = self._mapping[normalized]
        except KeyError as error:
            raise ValueError(
                f"Product code not found for name {normalized!r}",
            ) from error
        return self._spec(code=code, name=normalized)

    @beartype
    def _spec(self, *, code: str, name: str) -> ProductSpec:
        return ProductSpec(
            product_code=code,
            name=name,
            unit=self.unit,
            pack_size=self.pack_size,
            min_stock=None,
            max_stock=None,
            allow_fraction=self.unit is not ProductUnit.PIECE,
            moysklad_quantity_factor=default_moysklad_quantity_factor(self.unit),
        )


@beartype
@dataclass(slots=True)
class FakeTechnicianWarehouseTransferReader(TechnicianWarehouseTransferReader):
    moves: tuple[ExternalWarehouseMove, ...] = ()

    async def ensure_supply_store_codes_exist(self, codes: tuple[str, ...]) -> None:
        _ = codes

    async def read_moves(
        self,
        *,
        technician_store_code: str,
        moment_from: datetime,
        moment_to: datetime,
    ) -> ReadMovesResult:
        _ = technician_store_code, moment_from, moment_to
        return ReadMovesResult(moves=self.moves, skipped_unresolved=0)


def default_form_answers(revision_token: str) -> list[dict[str, str]]:
    return [
        {"title": FORM_TOKEN_FIELD_NAME, "value": revision_token},
        {"title": "Кофе", "value": "2"},
    ]


def inventory_form_answers(form_token: str) -> list[dict[str, str]]:
    return [
        {"title": FORM_TOKEN_FIELD_NAME, "value": form_token},
        {"title": "Кофе", "value": "1"},
    ]


@beartype
@dataclass(frozen=True, slots=True)
class WebhookPipelineStack:
    event_store: MongoEventStore
    outbox_store: MongoOutboxStore
    form_submission_store: MongoFormSubmissionStore
    photo_batch_store: MongoPhotoBatchStore
    accept_loading_photos: AcceptLoadingPhotosService
    photo_storage: InMemoryPhotoStorage
    outbox_worker: OutboxWorker
    webhook_client: TestClient
    machine_sales_store: MongoMachineSalesStore
    coffee_recipe_repo: MongoCoffeeRecipeRepository
    domain_product_store: FakeDomainProductStore
    reconciliation_repo: MongoPeriodReconciliationRepository
    settlement_repository: MongoTechnicianSettlementRepository
    settlement_event_store: MongoTechnicianSettlementEventStore
    residual_repo: MongoReconciliationResidualDocumentRepository
    refresh_pending: RefreshPendingWithAccountability
    preview_reconciliation: PreviewTechnicianReconciliation
    finalize_reconciliation: FinalizeTechnicianReconciliation
    warehouse_repository: TechnicianWarehouseRepository
    warehouse_importer: ImportTechnicianWarehouseTransfers
    inventory_telegram_bot: Bot


RevisionPipelineStack = WebhookPipelineStack
WarehouseSettlementStack = WebhookPipelineStack


@beartype
def build_webhook_pipeline_stack(
    database: Database,
    *,
    warehouse_moves: tuple[ExternalWarehouseMove, ...] = (),
    supply_store_codes: tuple[str, ...] = ("main",),
    warehouse_delta_port: TechnicianWarehouseDeltaPort | None = None,
    product_mapping: dict[str, str] | None = None,
    product_aliases: dict[str, str] | None = None,
    pack_size: Decimal = Decimal("20"),
    unit: ProductUnit = ProductUnit.GRAM,
) -> WebhookPipelineStack:
    event_store = MongoEventStore.from_collection(database["machine_events"])
    service_rules = ServiceRulesSettings()
    outbox_store = MongoOutboxStore.from_collection(
        database["domain_event_outbox"],
        max_attempts=3,
    )
    form_submission_store = MongoFormSubmissionStore.from_collection(
        database["form_submissions"],
    )
    repository = EventSourcedMachineOperationsRepository(
        event_store=event_store,
        revision_interval_min_days=service_rules.revision_interval_min_days,
        revision_interval_max_days=service_rules.revision_interval_max_days,
    )
    publisher = OutboxDomainEventPublisher(store=outbox_store)
    photo_batch_store = MongoPhotoBatchStore.from_collection(
        database["photo_batches"],
    )
    product_code_resolver = CatalogProductCodeResolver(
        product_mapping or {"Кофе": "coffee-1"},
        _aliases=product_aliases or {},
        pack_size=pack_size,
        unit=unit,
    )
    processors = OutboxProcessorRegistry()
    photo_storage = InMemoryPhotoStorage()

    directory_provider = ReferenceDataProvider()
    directory_provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [
            ["Id", "Имя"],
            [TEST_TECHNICIAN_ID.value, "Техник"],
            [OTHER_TECHNICIAN_ID.value, "Техник"],
            ["tech-integration", "Техник"],
        ],
    )

    class _StubVendingMachineRepository:
        def get(self, machine_id: MachineId) -> VendingMachine | None:
            return VendingMachine(id=machine_id, name=machine_id.value)

        def find_technician_display_name_for_machine(
            self,
            machine_id: MachineId,
        ) -> str | None:
            return "Техник"

        def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
            directory = directory_provider.technicians_directory_or_none()
            if directory is None:
                return None
            name = directory.names_by_id.get(technician_id)
            if name is None:
                return None
            stripped = name.strip()
            return stripped or None

        def list_available_for_technician(
            self,
            technician_id: TechnicianId,
        ) -> list[VendingMachine]:
            return []

        def list_all(self) -> list[VendingMachine]:
            return []

        def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
            return None

    class _RecordingTelegramNotifier:
        async def notify_batch(self, **kwargs: object) -> tuple[int, ...]:
            return (501,)

    stub_vending_machines = _StubVendingMachineRepository()
    record_duplicate = RecordPhotoDuplicateSuspectedService(
        executor=TechnicianAccountabilityExecutor(
            repository=InMemoryTechnicianAccountabilityRepository(
                event_store=InMemoryTechnicianAccountabilityEventStore(),
            ),
        ),
    )
    machine_sales_store = MongoMachineSalesStore.from_collection(database["machine_sales"])
    coffee_recipe_repo = MongoCoffeeRecipeRepository.from_collection(
        database["coffee_recipes"],
    )
    domain_product_store = FakeDomainProductStore()
    reconciliation_repo = MongoPeriodReconciliationRepository.from_collection(
        database["responsibility_period_reconciliations"],
    )
    revision_history_reader = EventStoreMachineRevisionHistoryReader(event_store=event_store)
    close_responsibility_period = build_integration_close_responsibility_period(
        form_submission_store=form_submission_store,
        revision_history=revision_history_reader,
        sales_store=machine_sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=coffee_recipe_repo,
        domain_product_store=domain_product_store,
        party_names_lookup=VendingMachinePeriodPartyNamesLookup(machines=stub_vending_machines),
        tolerance_seconds=0,
    )
    settlement_event_store = MongoTechnicianSettlementEventStore.from_collection(
        database["technician_settlement_events"],
    )
    settlement_repository = MongoTechnicianSettlementRepository(
        event_store=settlement_event_store,
    )
    settlement_executor = TechnicianSettlementExecutor(
        repository=settlement_repository,
    )
    post_accountability = PostPeriodAccountability(
        settlement_executor=settlement_executor,
        reconciliation_repo=reconciliation_repo,
    )
    side_effect_registry: ExternalSideEffectRegistry | None = InMemoryExternalSideEffectRegistry()
    telegram_notifier_ref = LoadingPhotosChatNotifierRef(_RecordingTelegramNotifier())  # type: ignore[arg-type]

    warehouse_event_store = MongoTechnicianWarehouseEventStore.from_collection(
        database["technician_warehouse_events"],
    )
    warehouse_repository = MongoTechnicianWarehouseRepository(event_store=warehouse_event_store)
    warehouse_executor = TechnicianWarehouseExecutor(
        repository=warehouse_repository,
        publisher=publisher,
    )
    observe_loading = ObserveTechnicianWarehouseLoading(executor=warehouse_executor)
    transfer_reader = FakeTechnicianWarehouseTransferReader(moves=warehouse_moves)
    catalog_specs: dict[str, ProductSpec] = {}
    for code in (product_mapping or {"Кофе": "coffee-1"}).values():
        catalog_specs[code.casefold()] = product_code_resolver.resolve_by_code(code)
    for alias in product_aliases or {}:
        catalog_specs[alias.casefold()] = product_code_resolver.resolve_by_code(alias)
    catalog_by_code = MappingProductSpecByCodeResolver(specs_by_code=catalog_specs)
    catalog_resolver = MoySkladCatalogBaseQuantityResolver(product_resolver=catalog_by_code)
    importer = ImportTechnicianWarehouseTransfers(
        reader=transfer_reader,
        catalog_base_quantity_resolver=catalog_resolver,
        executor=warehouse_executor,
        supply_store_codes=supply_store_codes,
        lookback_days=60,
    )
    resolved_delta_port: TechnicianWarehouseDeltaPort = (
        warehouse_delta_port
        if warehouse_delta_port is not None
        else TechnicianWarehouseDeltaService(
            importer=importer,
            executor=warehouse_executor,
        )
    )
    accept_warehouse_inventory = AcceptTechnicianWarehouseInventoryService(
        form_submission_store=form_submission_store,
        product_code_resolver=product_code_resolver,
        form_token_field_name=FORM_TOKEN_FIELD_NAME,
        executor=warehouse_executor,
    )
    warehouse_finalize = WarehouseSessionFinalizeAdapter(executor=warehouse_executor)

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=OutboxHandlerDeps(
            form_submission_store=form_submission_store,
            observe_technician_warehouse_loading=observe_loading,
            photo_batch_store=photo_batch_store,
            photo_storage=photo_storage,
            photo_downloader_ref=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
            loading_photos_notifier_ref=telegram_notifier_ref,
            integrity_alert_notifier_ref=PhotoIntegrityAlertNotifierRef(
                NoOpPhotoIntegrityAlertNotifier(),
            ),
            hash_index=MongoPhotoContentHashIndex.from_collection(
                database["photo_content_hashes"],
            ),
            finding_store=MongoPhotoIntegrityFindingStore.from_collection(
                database["photo_integrity_findings"],
            ),
            record_duplicate=record_duplicate,
            vending_machine_repository=stub_vending_machines,
            service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
            object_storage_key_prefix="",
            photo_integrity_enabled=True,
            include_loading_photos_telegram=True,
            machine_sales_store=machine_sales_store,
            coffee_recipe_repo=coffee_recipe_repo,
            domain_product_store=domain_product_store,
            reconciliation_repo=reconciliation_repo,
            revision_history=revision_history_reader,
            close_responsibility_period=close_responsibility_period,
            post_accountability=post_accountability,
            side_effect_registry=side_effect_registry,
        ),
    )

    refresh_pending = RefreshPendingWithAccountability(
        refresh=RefreshPendingPeriodReconciliations(
            repo=reconciliation_repo,
            sales_store=machine_sales_store,
            coffee_recipe_repo=coffee_recipe_repo,
            domain_product_store=domain_product_store,
            form_submission_store=form_submission_store,
            revision_history=revision_history_reader,
            tolerance_seconds=0,
        ),
        post_accountability=post_accountability,
    )
    residual_repo = MongoReconciliationResidualDocumentRepository.from_collection(
        database["reconciliation_residual_documents"],
    )
    draft_store = MongoReconciliationDraftStore.from_collection(
        database["reconciliation_drafts"],
    )
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=reconciliation_repo,
        settlement_repository=settlement_repository,
        warehouse_delta_port=resolved_delta_port,
        warehouse_repository=warehouse_repository,
        importer=importer,
    )
    preview_reconciliation = PreviewTechnicianReconciliation(
        planner=planner,
        draft_store=draft_store,
    )
    finalize_reconciliation = FinalizeTechnicianReconciliation(
        draft_store=draft_store,
        warehouse_repository=warehouse_repository,
        settlement_executor=settlement_executor,
        settlement_repository=settlement_repository,
        reconciliation_repo=reconciliation_repo,
        residual_repo=residual_repo,
        warehouse_finalize=warehouse_finalize,
    )

    outbox_worker = OutboxWorker(store=outbox_store, processors=processors)

    executor = MachineOperationsExecutor(
        repository=repository,
        publisher=publisher,
    )
    accept_revision_form_submission = AcceptRevisionFormSubmissionService(
        form_submission_store=form_submission_store,
        register_revision_from_form=RegisterRevisionFromFormService(executor=executor),
        product_code_resolver=product_code_resolver,
        form_token_field_name=FORM_TOKEN_FIELD_NAME,
    )
    register_loading_photos = RegisterLoadingPhotosService(
        executor=executor,
        machine_operations=repository,
        last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
        maintenance_cooldown_minutes=0,
    )
    accept_loading_photos = AcceptLoadingPhotosService(
        photo_batch_store=photo_batch_store,
        register_loading_photos=register_loading_photos,
        loading_photos_min_count=2,
        loading_photos_max_count=10,
    )
    accept_inventory_form_submission = AcceptInventoryFormSubmissionService(
        form_submission_store=form_submission_store,
        register_loading_from_form=RegisterLoadingFromFormService(executor=executor),
        product_code_resolver=product_code_resolver,
        form_token_field_name=FORM_TOKEN_FIELD_NAME,
    )
    telegram_user_resolver = create_autospec(TelegramUserResolver, instance=True)
    warehouse_bot_user = SystemUser(
        user_id=SystemUserId("integration-warehouse-user"),
        name="Integration Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=424242,
        technician_id=TEST_TECHNICIAN_ID,
        company_roles=frozenset(),
    )

    def _resolve_telegram_user(technician_id: TechnicianId) -> SystemUser | None:
        if technician_id == TEST_TECHNICIAN_ID:
            return warehouse_bot_user
        return None

    telegram_user_resolver.find_by_technician_id.side_effect = _resolve_telegram_user
    inventory_telegram_bot = create_autospec(Bot, instance=True)
    inventory_telegram_bot.send_message = AsyncMock()
    inventory_telegram_handler = TechnicianWarehouseInventoryTelegramHandler(
        telegram_user_resolver=telegram_user_resolver,
        bot=inventory_telegram_bot,
    )
    processors.register(
        TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
        cast(OutboxHandler, inventory_telegram_handler.process),
    )
    publisher.subscribe(
        TechnicianWarehouseInventoryCounted,
        TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
    )
    webhook_client = TestClient(
        build_google_forms_webhook_app(
            GoogleFormsWebhookDeps(
                accept_revision_form_submission=accept_revision_form_submission,
                accept_inventory_form_submission=accept_inventory_form_submission,
                accept_technician_warehouse_inventory=accept_warehouse_inventory,
                form_workflow_notifier=FormWorkflowNotifierRef(
                    NoOpFormWorkflowNotifier(),
                ),
                direct_warehouse_chat_notifier=NoOpDirectWarehouseChatNotifier(),
                telegram_user_resolver=telegram_user_resolver,
                bot=WebhookPlaceholderBot(),
                token_field_name=FORM_TOKEN_FIELD_NAME,
                webhook_secret=WEBHOOK_SECRET,
                webhook_signature_max_age_seconds=WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
                revision_form_token_secret=FORM_TOKEN_SECRET,
                inventory_form_token_secret=INVENTORY_FORM_TOKEN_SECRET,
                technician_warehouse_inventory_form_token_secret=(
                    WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET
                ),
                verify_revision_form_token=verify_revision_form_token,
                verify_inventory_form_token=verify_inventory_form_token,
                verify_technician_warehouse_inventory_token=verify_technician_warehouse_inventory_token,
                peek_form_token=peek_form_token,
            ),
        ),
    )

    return WebhookPipelineStack(
        event_store=event_store,
        outbox_store=outbox_store,
        form_submission_store=form_submission_store,
        photo_batch_store=photo_batch_store,
        accept_loading_photos=accept_loading_photos,
        photo_storage=photo_storage,
        outbox_worker=outbox_worker,
        webhook_client=webhook_client,
        machine_sales_store=machine_sales_store,
        coffee_recipe_repo=coffee_recipe_repo,
        domain_product_store=domain_product_store,
        reconciliation_repo=reconciliation_repo,
        settlement_repository=settlement_repository,
        settlement_event_store=settlement_event_store,
        residual_repo=residual_repo,
        refresh_pending=refresh_pending,
        preview_reconciliation=preview_reconciliation,
        finalize_reconciliation=finalize_reconciliation,
        warehouse_repository=warehouse_repository,
        warehouse_importer=importer,
        inventory_telegram_bot=inventory_telegram_bot,
    )


build_revision_pipeline_stack = build_webhook_pipeline_stack
build_warehouse_settlement_stack = build_webhook_pipeline_stack
