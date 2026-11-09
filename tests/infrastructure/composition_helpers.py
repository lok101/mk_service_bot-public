from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype
from pydantic import SecretStr

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import (
    CompleteMaintenanceService,
    CreateLoadingFormService,
    GetServiceCapabilitiesService,
    GetTechnicianRevisionOutlookService,
    ListAvailableMachinesService,
    RegisterLoadingFromFormService,
    RegisterLoadingPhotosService,
    RegisterRevisionFromFormService,
)
from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    InMemoryTechnicianStore,
)
from src.application.photo_batches.accept import AcceptLoadingPhotosService
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_integrity import PhotoIntegrityAlertNotifierRef
from src.application.reference_data import ReferenceDataProvider, SyncReferenceData
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.technician_warehouse.accept_inventory import (
    AcceptTechnicianWarehouseInventoryService,
)
from src.application.technician_warehouse.close_warehouse import CloseTechnicianWarehouse
from src.application.technician_warehouse.delta import TechnicianWarehouseDeltaService
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.application.technician_warehouse.ports import (
    ReadMovesResult,
    TechnicianWarehouseTransferReader,
)
from src.config.telegram import TelegramSettings
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.form_tokens import (
    build_verify_inventory_form_token,
    build_verify_revision_form_token,
    peek_form_token,
    verify_technician_warehouse_inventory_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.domain.system_user import SystemUser
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
from src.infrastructure.composition.container import AppContainer
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.form_workflow.memory import InMemoryFormWorkflowSessionStore
from src.infrastructure.integrations.google.forms import (
    GoogleFormsLoadingFormLinkProvider,
    GoogleFormsRevisionFormLinkProvider,
)
from src.infrastructure.integrations.google.forms.link_providers import (
    GoogleFormsTechnicianWarehouseInventoryLinkProvider,
)
from src.infrastructure.integrations.moysklad.product_spec_resolver import (
    MappingProductSpecByCodeResolver,
)
from src.infrastructure.integrations.moysklad.warehouse_move_quantity import (
    MoySkladCatalogBaseQuantityResolver,
)
from src.infrastructure.machine_operations.maintenance_cooldown_bypass_memory import (
    NullMaintenanceCooldownBypassReader,
)
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.settlement_publisher import SettlementOutboxPublisher
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.stubs import (
    InMemoryPhotoStorage,
    StubTelegramPhotoDownloader,
)
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore
from src.infrastructure.reference_data.worker import ReferenceDataSyncWorker
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)
from src.infrastructure.testing.stubs import PassThroughProductCodeResolver
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    NoOpDirectWarehouseChatNotifier,
    WebhookPlaceholderBot,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier
from src.interfaces.telegram.loading_photos_notifier import NoOpLoadingPhotosChatNotifier
from src.interfaces.telegram.machines.deps import MachineDialogDeps
from src.interfaces.telegram.photo_integrity_alert_notifier import NoOpPhotoIntegrityAlertNotifier


class _StubVendingMachineRepository:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name=machine_id.value)

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        return None

    def find_technician_display_name(
        self,
        technician_id: TechnicianId,
    ) -> str | None:
        return None

    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


class _StubTelegramUserResolver:
    def resolve(self, telegram_user_id: int) -> SystemUser | None:
        return None

    def find_by_technician_id(self, technician_id: TechnicianId) -> SystemUser | None:
        return None


class _EmptyReferenceDataReader:
    def read_rows(self, source_id):
        return []


@beartype
@dataclass(slots=True)
class _EmptyTechnicianWarehouseTransferReader(TechnicianWarehouseTransferReader):
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
        return ReadMovesResult(moves=(), skipped_unresolved=0)


@beartype
def _build_minimal_technician_warehouse_bundle(
    *,
    submission_store: InMemoryFormSubmissionStore,
    product_code_resolver: PassThroughProductCodeResolver,
    form_token_field_name: str,
) -> TechnicianWarehouseBundle:
    warehouse_repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    warehouse_executor = TechnicianWarehouseExecutor(repository=warehouse_repository)
    warehouse_importer = ImportTechnicianWarehouseTransfers(
        reader=_EmptyTechnicianWarehouseTransferReader(),
        catalog_base_quantity_resolver=MoySkladCatalogBaseQuantityResolver(
            product_resolver=MappingProductSpecByCodeResolver(specs_by_code={}),
        ),
        executor=warehouse_executor,
        supply_store_codes=("main",),
        lookback_days=60,
    )
    return TechnicianWarehouseBundle(
        executor=warehouse_executor,
        event_store=warehouse_repository.event_store,
        importer=warehouse_importer,
        delta_port=TechnicianWarehouseDeltaService(
            importer=warehouse_importer,
            executor=warehouse_executor,
        ),
        accept_inventory=AcceptTechnicianWarehouseInventoryService(
            form_submission_store=submission_store,
            product_code_resolver=product_code_resolver,
            form_token_field_name=form_token_field_name,
            executor=warehouse_executor,
        ),
        link_provider=GoogleFormsTechnicianWarehouseInventoryLinkProvider(
            form_url="https://example.com/warehouse",
            token_entry_id="entry.1",
            token_secret="warehouse-secret",
            clock=lambda: datetime.now(tz=UTC),
        ),
        observe_loading=ObserveTechnicianWarehouseLoading(executor=warehouse_executor),
        close_warehouse=CloseTechnicianWarehouse(
            executor=warehouse_executor,
            importer=warehouse_importer,
        ),
    )


@beartype
def build_minimal_container(
    *,
    telegram_settings: TelegramSettings | None = None,
) -> AppContainer:
    telegram = telegram_settings or TelegramSettings.model_construct(
        bot_token=SecretStr("dev-bot-token-16chars"),
        webhook_public_host="",
    )
    outbox_store = InMemoryOutboxStore()
    processors = OutboxProcessorRegistry()
    publisher = OutboxDomainEventPublisher(store=outbox_store)
    settlement_publisher = SettlementOutboxPublisher(store=outbox_store)
    event_store = InMemoryEventStore()
    repository = EventSourcedMachineOperationsRepository(event_store=event_store)
    technician_last_maintenance = InMemoryTechnicianLastMaintenanceProjection()
    executor = MachineOperationsExecutor(
        repository=repository,
        publisher=publisher,
        technician_last_maintenance=technician_last_maintenance,
    )
    cooldown_minutes = 20
    bypass_reader = NullMaintenanceCooldownBypassReader()
    service_calendar_timezone = DEFAULT_SERVICE_CALENDAR_TIMEZONE
    submission_store = InMemoryFormSubmissionStore()
    product_code_resolver = PassThroughProductCodeResolver()
    register_revision = RegisterRevisionFromFormService(executor=executor)
    register_loading = RegisterLoadingFromFormService(executor=executor)
    register_loading_photos = RegisterLoadingPhotosService(
        executor=executor,
        machine_operations=repository,
        last_maintenance_reader=technician_last_maintenance,
        maintenance_cooldown_minutes=cooldown_minutes,
        bypass_reader=bypass_reader,
        service_calendar_timezone=service_calendar_timezone,
    )
    photo_batch_store = InMemoryPhotoBatchStore()
    stub_vending_machines = _StubVendingMachineRepository()
    revision_form_links = GoogleFormsRevisionFormLinkProvider(
        form_url="https://example.com/revision",
        token_entry_id="entry.1",
        token_secret="secret",
    )
    loading_form_links = GoogleFormsLoadingFormLinkProvider(
        form_url="https://example.com/loading",
        token_entry_id="entry.2",
        token_secret="secret",
    )
    machine_ops = MachineOpsBundle(
        event_store=event_store,
        repository=repository,
        executor=executor,
        technician_last_maintenance=technician_last_maintenance,
        vending_machines=stub_vending_machines,
        revision_form_links=revision_form_links,
        loading_form_links=loading_form_links,
        list_available_machines=ListAvailableMachinesService(repository=stub_vending_machines),
        get_service_capabilities=GetServiceCapabilitiesService(
            machine_operations=repository,
            revision_form_links=revision_form_links,
            last_maintenance_reader=technician_last_maintenance,
            maintenance_cooldown_minutes=cooldown_minutes,
            bypass_reader=bypass_reader,
            service_calendar_timezone=service_calendar_timezone,
        ),
        get_technician_revision_outlook=GetTechnicianRevisionOutlookService(
            machine_operations=repository,
            vending_machines=stub_vending_machines,
        ),
        complete_maintenance=CompleteMaintenanceService(
            executor=executor,
            last_maintenance_reader=technician_last_maintenance,
            maintenance_cooldown_minutes=cooldown_minutes,
            bypass_reader=bypass_reader,
            service_calendar_timezone=service_calendar_timezone,
        ),
        create_loading_form=CreateLoadingFormService(form_links=loading_form_links),
        maintenance_cooldown_bypass=bypass_reader,
        service_calendar_timezone=service_calendar_timezone,
        maintenance_cooldown_minutes=cooldown_minutes,
    )
    photos = PhotoPipelineBundle(
        batch_store=photo_batch_store,
        storage=InMemoryPhotoStorage(),
        accept_loading_photos=AcceptLoadingPhotosService(
            photo_batch_store=photo_batch_store,
            register_loading_photos=register_loading_photos,
            loading_photos_min_count=2,
            loading_photos_max_count=10,
        ),
        downloader_ref=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
        loading_photos_notifier_ref=LoadingPhotosChatNotifierRef(NoOpLoadingPhotosChatNotifier()),
        integrity_alert_notifier_ref=PhotoIntegrityAlertNotifierRef(
            NoOpPhotoIntegrityAlertNotifier(),
        ),
        form_workflow_notifier_ref=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
    )
    outbox = OutboxBundle(
        publisher=publisher,
        processors=processors,
        worker=OutboxWorker(store=outbox_store, processors=processors),
        settlement_publisher=settlement_publisher,
    )
    config = AppConfig(
        bot_token=telegram.bot_token.get_secret_value(),
        telegram_webhook_public_host=telegram.webhook_public_host,
        telegram_webhook_path=telegram.webhook_path,
        telegram_webhook_secret=telegram.webhook_secret_value(),
        api_host="127.0.0.1",
        api_port=8000,
        api_log_level="info",
        webhook_secret="test-webhook-secret",
        webhook_signature_max_age_seconds=300,
        webhook_max_body_bytes=1_000_000,
        revision_form_token_secret="revision-secret",
        inventory_form_token_secret="inventory-secret",
        form_token_field_name="token",
        form_token_ttl_hours=24.0,
    )
    technician_warehouse = _build_minimal_technician_warehouse_bundle(
        submission_store=submission_store,
        product_code_resolver=product_code_resolver,
        form_token_field_name=config.form_token_field_name,
    )
    accept_revision = AcceptRevisionFormSubmissionService(
        form_submission_store=submission_store,
        register_revision_from_form=register_revision,
        product_code_resolver=product_code_resolver,
        form_token_field_name=config.form_token_field_name,
    )
    accept_inventory = AcceptInventoryFormSubmissionService(
        form_submission_store=submission_store,
        register_loading_from_form=register_loading,
        product_code_resolver=product_code_resolver,
        form_token_field_name=config.form_token_field_name,
    )
    telegram_user_resolver = _StubTelegramUserResolver()
    forms = FormsBundle(
        submission_store=submission_store,
        workflow_session_store=InMemoryFormWorkflowSessionStore(),
        telegram_user_resolver=telegram_user_resolver,
        accept_revision=accept_revision,
        accept_inventory=accept_inventory,
        webhook_deps=GoogleFormsWebhookDeps(
            accept_revision_form_submission=accept_revision,
            accept_technician_warehouse_inventory=technician_warehouse.accept_inventory,
            accept_inventory_form_submission=accept_inventory,
            form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
            direct_warehouse_chat_notifier=NoOpDirectWarehouseChatNotifier(),
            telegram_user_resolver=telegram_user_resolver,
            bot=WebhookPlaceholderBot(),
            token_field_name=config.form_token_field_name,
            webhook_secret=config.webhook_secret,
            webhook_signature_max_age_seconds=config.webhook_signature_max_age_seconds,
            webhook_max_body_bytes=config.webhook_max_body_bytes,
            revision_form_token_secret=config.revision_form_token_secret,
            inventory_form_token_secret=config.inventory_form_token_secret,
            technician_warehouse_inventory_form_token_secret="warehouse-secret",
            verify_revision_form_token=build_verify_revision_form_token(
                max_age_hours=config.form_token_ttl_hours,
            ),
            verify_inventory_form_token=build_verify_inventory_form_token(
                max_age_hours=config.form_token_ttl_hours,
            ),
            verify_technician_warehouse_inventory_token=verify_technician_warehouse_inventory_token,
            peek_form_token=peek_form_token,
        ),
    )
    settlement = SettlementBundle(
        sales_ingest_worker=None,
        kitshop_sales_ingest_worker=None,
        kitvending_client=object(),
        company_occupancy_store=InMemoryMachineCompanyOccupancyStore(),
    )
    reference_provider = ReferenceDataProvider()
    reference_store = InMemoryReferenceDataSnapshotStore()
    reference_sync = SyncReferenceData(
        reader=_EmptyReferenceDataReader(),
        store=reference_store,
        provider=reference_provider,
        source_ids=(),
    )
    reference_data = ReferenceDataBundle(
        provider=reference_provider,
        store=reference_store,
        roster_store=InMemoryLocationRosterStore(),
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        master_data_stores=InMemoryMasterDataStores(),
        system_user_store=InMemorySystemUserStore(),
        technician_store=InMemoryTechnicianStore(),
        sync=reference_sync,
        worker=ReferenceDataSyncWorker(
            sync=reference_sync,
            store=reference_store,
            sync_interval_seconds=300,
            staleness_alert_seconds=1800,
        ),
    )
    return AppContainer(
        config=config,
        persistence=PersistenceBundle(mongo_client=None, redis_client=None),
        machine_ops=machine_ops,
        forms=forms,
        outbox=outbox,
        photos=photos,
        settlement=settlement,
        reference_data=reference_data,
        technician_warehouse=technician_warehouse,
        telegram=TelegramBundle(
            machine_dialog_deps=MachineDialogDeps(
                telegram_user_resolver=telegram_user_resolver,
                technician_warehouse_inventory_link_provider=technician_warehouse.link_provider,
            ),
            visit_store=InMemoryServiceVisitStore(),
        ),
    )
