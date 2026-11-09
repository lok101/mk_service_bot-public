from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.application.micromarket_loading.planogram import MicromarketPlanogram
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.outbox.handler_ids import (
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID,
    MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
    PERIOD_RECONCILIATION_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
    SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
    TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
    TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
)
from src.application.photo_batches.downloader_ref import PhotoDownloaderRef
from src.application.photo_batches.notifier_ref import LoadingPhotosChatNotifierRef
from src.application.photo_integrity import PhotoIntegrityAlertNotifierRef
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.technician_accountability.executor import TechnicianAccountabilityExecutor
from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.domain.calendar import DEFAULT_SERVICE_CALENDAR_TIMEZONE
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.domain.models import VendingMachine
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.composition.adapters.machine_sales_qty_baseline_lookup import (
    MachineSalesStoreQtyBaselineLookup,
)
from src.infrastructure.composition.wiring.deps import OutboxHandlerDeps
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    _baseline_lookup_for_deps,
    register_outbox_handlers,
)
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore
from src.infrastructure.photo_batches.memory_integrity import (
    InMemoryPhotoContentHashIndex,
    InMemoryPhotoIntegrityFindingStore,
)
from src.infrastructure.photo_batches.stubs import (
    InMemoryPhotoStorage,
    StubTelegramPhotoDownloader,
)
from src.infrastructure.technician_accountability.memory import (
    InMemoryTechnicianAccountabilityEventStore,
    InMemoryTechnicianAccountabilityRepository,
)
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
)
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineRevisionHistoryReader,
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)
from src.interfaces.telegram.loading_photos_notifier import NoOpLoadingPhotosChatNotifier
from src.interfaces.telegram.photo_integrity_alert_notifier import NoOpPhotoIntegrityAlertNotifier


class _StubVendingMachineRepository:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name=machine_id.value)

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        return "Техник"

    def find_technician_display_name(
        self,
        technician_id: TechnicianId,
    ) -> str | None:
        return "Техник"

    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


class _StubPeriodPartyNamesLookup:
    def location_name(self, machine_id: MachineId) -> str | None:
        return machine_id.value

    def technician_name(self, technician_id: TechnicianId) -> str | None:
        return technician_id.value


def _minimal_outbox_handler_deps(
    *,
    include_loading_photos_telegram: bool = True,
    include_post_accountability: bool = True,
) -> OutboxHandlerDeps:
    form_submission_store = InMemoryFormSubmissionStore()
    record_duplicate = RecordPhotoDuplicateSuspectedService(
        executor=TechnicianAccountabilityExecutor(
            repository=InMemoryTechnicianAccountabilityRepository(
                event_store=InMemoryTechnicianAccountabilityEventStore(),
            ),
        ),
    )
    close_responsibility_period: CloseResponsibilityPeriodOnRevision | None = None
    machine_sales_store = None
    coffee_recipe_repo = None
    domain_product_store = FakeDomainProductStore()
    reconciliation_repo = None
    revision_history = None
    post_accountability = None

    if include_post_accountability:
        machine_sales_store = InMemoryMachineSalesStore()
        coffee_recipe_repo = InMemoryCoffeeRecipeRepository()
        domain_product_store = FakeDomainProductStore()
        reconciliation_repo = InMemoryPeriodReconciliationRepository()
        revision_history = InMemoryMachineRevisionHistoryReader()
        close_responsibility_period = CloseResponsibilityPeriodOnRevision(
            form_submission_store=form_submission_store,
            revision_history=revision_history,
            sales_store=machine_sales_store,
            reconciliation_repo=reconciliation_repo,
            coffee_recipe_repo=coffee_recipe_repo,
            domain_product_store=domain_product_store,
            tolerance_seconds=0,
            party_names_lookup=_StubPeriodPartyNamesLookup(),
        )
        settlement_repo = InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        )
        post_accountability = PostPeriodAccountability(
            settlement_executor=TechnicianSettlementExecutor(repository=settlement_repo),
            reconciliation_repo=reconciliation_repo,
        )

    return OutboxHandlerDeps(
        form_submission_store=form_submission_store,
        observe_technician_warehouse_loading=ObserveTechnicianWarehouseLoading(
            executor=TechnicianWarehouseExecutor(
                repository=InMemoryTechnicianWarehouseRepository(
                    event_store=InMemoryTechnicianWarehouseEventStore(),
                ),
            ),
        ),
        photo_batch_store=InMemoryPhotoBatchStore(),
        photo_storage=InMemoryPhotoStorage(),
        photo_downloader_ref=PhotoDownloaderRef(StubTelegramPhotoDownloader()),
        loading_photos_notifier_ref=LoadingPhotosChatNotifierRef(NoOpLoadingPhotosChatNotifier()),
        integrity_alert_notifier_ref=PhotoIntegrityAlertNotifierRef(
            NoOpPhotoIntegrityAlertNotifier(),
        ),
        hash_index=InMemoryPhotoContentHashIndex(),
        finding_store=InMemoryPhotoIntegrityFindingStore(),
        record_duplicate=record_duplicate,
        vending_machine_repository=_StubVendingMachineRepository(),
        service_timezone=DEFAULT_SERVICE_CALENDAR_TIMEZONE,
        object_storage_key_prefix="",
        photo_integrity_enabled=True,
        include_loading_photos_telegram=include_loading_photos_telegram,
        machine_sales_store=machine_sales_store,
        coffee_recipe_repo=coffee_recipe_repo,
        domain_product_store=domain_product_store,
        reconciliation_repo=reconciliation_repo,
        revision_history=revision_history,
        close_responsibility_period=close_responsibility_period,
        post_accountability=post_accountability,
        service_visit_store=InMemoryServiceVisitStore(),
    )


def test_baseline_lookup_for_deps_uses_sales_baseline_timezone() -> None:
    """Baseline day-bucketing follows SALES_MONITORING_TZ, not SERVICE_DISPLAY_TIMEZONE."""
    service_tz = ZoneInfo("Europe/Moscow")
    sales_tz = ZoneInfo("Asia/Yekaterinburg")
    assert service_tz != sales_tz
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=True),
        service_timezone=service_tz,
        sales_baseline_timezone=sales_tz,
        machine_sales_store=InMemoryMachineSalesStore(),
    )

    lookup = _baseline_lookup_for_deps(deps)

    assert isinstance(lookup, MachineSalesStoreQtyBaselineLookup)
    assert lookup.timezone is sales_tz


def test_revision_inventory_handler_not_registered() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
    )
    assert not processors.is_registered("revision_inventory")
    assert "revision_inventory" not in publisher._handler_ids_by_event_type.get(
        RevisionCompleted,
        [],
    )


def test_loading_move_handler_not_registered() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
    )
    assert not processors.is_registered("loading_move")
    assert "loading_move" not in publisher._handler_ids_by_event_type.get(
        LoadingSubmitted,
        [],
    )


def test_technician_warehouse_loading_still_registered() -> None:
    effects_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    effects_processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=effects_publisher,
        processors=effects_processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
        process="effects",
    )
    assert effects_processors.is_registered(TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID)
    assert TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID not in effects_publisher.handler_ids_for(
        LoadingSubmitted,
    )

    ingress_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    register_outbox_handlers(
        publisher=ingress_publisher,
        processors=OutboxProcessorRegistry(),
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
        process="ingress",
    )
    assert TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID in ingress_publisher.handler_ids_for(
        LoadingSubmitted,
    )


def test_register_outbox_handlers_registers_all_core_handler_ids() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = _minimal_outbox_handler_deps(include_post_accountability=True)
    assert deps.post_accountability is not None

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )

    for handler_id in (
        TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
        LOADING_PHOTOS_HANDLER_ID,
        LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
        PERIOD_RECONCILIATION_HANDLER_ID,
        SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
    ):
        assert processors.is_registered(handler_id), handler_id
    assert not processors.is_registered(SERVICE_VISIT_INCIDENT_HANDLER_ID)

    ingress_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    register_outbox_handlers(
        publisher=ingress_publisher,
        processors=OutboxProcessorRegistry(),
        deps=deps,
        process="ingress",
    )
    assert PERIOD_RECONCILIATION_HANDLER_ID in ingress_publisher.handler_ids_for(
        RevisionCompleted,
    )
    assert SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID in ingress_publisher.handler_ids_for(
        MaintenanceCompleted,
    )
    assert SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID in ingress_publisher.handler_ids_for(
        PhotosSubmitted,
    )
    assert LOADING_PHOTOS_TELEGRAM_HANDLER_ID in ingress_publisher.handler_ids_for(
        PhotosSubmitted,
    )


def test_core_registration_subscribes_service_visit_handler_to_photo_event() -> None:
    publisher = _registered_publisher()
    assert SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID in publisher._handler_ids_by_event_type.get(
        PhotosSubmitted,
        [],
    )
    assert SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID in publisher._handler_ids_by_event_type.get(
        MaintenanceCompleted,
        [],
    )


def test_publish_composite_photo_enqueues_photo_and_service_visit_handlers() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
    )
    at = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Yekaterinburg"))
    event = PhotosSubmitted(
        event_id=EventId("photo-composite-publish-1"),
        batch_id=BatchId("batch-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        photo_count=2,
        submitted_at=at,
        occurred_at=at,
        maintenance_completed_at=at,
    )

    publisher.publish(event)

    pairs = {(entry["event_id"], entry["handler_id"]) for entry in store._entries.values()}
    event_id = event.event_id.value
    assert (event_id, LOADING_PHOTOS_HANDLER_ID) in pairs
    assert (event_id, LOADING_PHOTOS_INTEGRITY_HANDLER_ID) in pairs
    assert (event_id, LOADING_PHOTOS_TELEGRAM_HANDLER_ID) in pairs
    assert (event_id, SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID) in pairs
    assert len({handler for eid, handler in pairs if eid == event_id}) == 4

    publisher.publish(event)
    assert len(store._entries) == 4


def test_register_outbox_handlers_skips_post_accountability_when_deps_none() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = _minimal_outbox_handler_deps(include_post_accountability=False)

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )

    assert not processors.is_registered(PERIOD_RECONCILIATION_HANDLER_ID)


def test_register_outbox_handlers_skips_telegram_photos_when_flag_false() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = _minimal_outbox_handler_deps(
        include_post_accountability=True,
        include_loading_photos_telegram=False,
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )

    assert not processors.is_registered(LOADING_PHOTOS_TELEGRAM_HANDLER_ID)
    ingress_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    register_outbox_handlers(
        publisher=ingress_publisher,
        processors=OutboxProcessorRegistry(),
        deps=deps,
        process="ingress",
    )
    assert LOADING_PHOTOS_TELEGRAM_HANDLER_ID not in ingress_publisher.handler_ids_for(
        PhotosSubmitted,
    )


def _registered_publisher() -> OutboxDomainEventPublisher:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
    )
    return publisher


def test_loading_submitted_has_warehouse_handler() -> None:
    publisher = _registered_publisher()
    ids = publisher.handler_ids_for(LoadingSubmitted)
    assert TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID in ids
    assert "loading_move" not in ids


def test_inventory_telegram_handler_not_in_core_registration() -> None:
    publisher = _registered_publisher()
    assert TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID not in publisher.handler_ids_for(
        TechnicianWarehouseInventoryCounted
    )


def test_register_outbox_handlers_registers_shop_list_publish_when_store_present() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    planogram = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=True),
        micromarket_planogram_store=planogram,
        micromarket_stock_store=stock_store,
    )
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )
    assert processors.is_registered(MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID)
    assert MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID in publisher.handler_ids_for(
        MicromarketShopListPublishRequested,
    )
    bound = processors._handlers[MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID]
    handler = bound.__self__
    from src.application.micromarket_loading import MicromarketShopListPublishHandler

    assert isinstance(handler, MicromarketShopListPublishHandler)
    assert handler.stock_store is stock_store
    assert handler.event_publisher is publisher


def test_register_outbox_handlers_skips_shop_list_publish_without_store() -> None:
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=OutboxDomainEventPublisher(store=InMemoryOutboxStore()),
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=True),
    )
    assert not processors.is_registered(MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID)


def test_missing_shop_gateway_accepts_catalog_names_and_sets_failed() -> None:
    planogram = InMemoryMicromarketPlanogramStore()
    planogram.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(),
            updated_at=datetime(2026, 10, 5, tzinfo=UTC),
            shop_list_status=ShopListPublishStatus.PUBLISHING,
            shop_list_publication_id="pub-missing-gw",
        ),
    )
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=True),
        micromarket_planogram_store=planogram,
        micromarket_shop_list_gateway=None,
    )
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )
    bound = processors._handlers[MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID]
    bound(
        MicromarketShopListPublishRequested(
            event_id=EventId("missing-gw-publish-1"),
            machine_code="701",
            publication_id="pub-missing-gw",
            lines=(("d-1001", "10", 6348, False),),
            occurred_at=datetime(2026, 10, 5, tzinfo=UTC),
        ),
    )
    updated = planogram.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert "Магазин Kit Shop" in updated.shop_list_error


def test_register_outbox_handlers_registers_post_visit_squeeze_when_present() -> None:
    from src.application.micromarket_loading.assembly_orders import LaunchFromAssemblyOrders
    from src.application.micromarket_loading.post_visit_squeeze import PostVisitSqueeze
    from src.application.outbox.micromarket_post_visit_squeeze import (
        MicromarketPostVisitSqueezeOutboxHandler,
    )
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketAssemblyOrderStore,
        InMemoryMicromarketDeviceStockStore,
        InMemoryMicromarketSalesAfter,
        InMemoryPendingMicromarketInventStore,
    )

    class _Alerter:
        def send(self, text: str) -> None:
            del text

    class _Cycle:
        def load(self, machine_code: str) -> None:
            del machine_code
            return None

        def save(self, cycle: object) -> None:
            del cycle

    class _Launch:
        def execute(self, *, machine_code: str) -> None:
            del machine_code
            return None

    cycle = _Cycle()
    squeeze = PostVisitSqueeze(
        pending_store=InMemoryPendingMicromarketInventStore(),
        launch_from_assembly=LaunchFromAssemblyOrders(
            assembly_store=InMemoryMicromarketAssemblyOrderStore(),
            cycle_store=cycle,  # type: ignore[arg-type]
            warehouse_stock=None,
            launch=_Launch(),  # type: ignore[arg-type]
        ),
        stock_store=InMemoryMicromarketDeviceStockStore(),
        sales_after=InMemoryMicromarketSalesAfter([]),
        alerter=_Alerter(),  # type: ignore[arg-type]
        cycle_store=cycle,  # type: ignore[arg-type]
    )
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=True),
        post_visit_squeeze=squeeze,
    )
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )
    assert processors.is_registered(MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID)
    assert MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID in publisher.handler_ids_for(
        MicromarketPostVisitSqueezeRequested,
    )
    bound = processors._handlers[MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID]
    assert isinstance(bound.__self__, MicromarketPostVisitSqueezeOutboxHandler)
