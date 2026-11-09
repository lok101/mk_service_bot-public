from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.machine_operations.additional_maintenance import (
    AlwaysDenyAdditionalMaintenance,
)
from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.ports import (
    AdditionalMaintenanceAllowed,
    LoadingFormLinkProvider,
    RevisionFormLinkProvider,
)
from src.application.machine_operations.services import (
    CompleteMaintenanceService,
    CreateLoadingFormService,
    GetServiceCapabilitiesService,
    GetTechnicianRevisionOutlookService,
    ListAvailableMachinesService,
)
from src.application.micromarket_loading.alert_sweep import SweepMicromarketLoadingAlerts
from src.application.micromarket_loading.complete_maintenance_gate import (
    MicromarketCompleteMaintenanceInventoryGate,
)
from src.application.micromarket_loading.sync_supply_order_category_facts import (
    SyncSupplyOrderCategoryFacts,
)
from src.application.micromarket_loading.sync_warehouse_stock import SyncMicromarketWarehouseStock
from src.application.reference_data import ReferenceDataProvider
from src.config.settings import Settings
from src.domain.micromarket_loading.order import MicromarketLoadingCycle
from src.infrastructure.composition.adapters.closable_extra_additional_maintenance import (
    ClosableExtraAdditionalMaintenance,
)
from src.infrastructure.composition.adapters.micromarket_loading_alerter import (
    VendingMachineNameLookup,
    build_micromarket_loading_alerter,
    build_micromarket_warehouse_stock_staleness_alerter,
)
from src.infrastructure.composition.bundles.machine_ops import MachineOpsBundle
from src.infrastructure.composition.factories import (
    build_domain_product_store,
    build_event_store,
    build_form_inventory_policy_store,
    build_maintenance_cooldown_bypass_reader,
    build_master_data_stores,
    build_micromarket_device_stock_store,
    build_micromarket_planogram_store,
    build_micromarket_warehouse_stock_snapshot_store,
    build_moysklad_client,
    build_service_visit_store,
    build_technician_last_maintenance_projection,
    build_vending_machine_repository,
)
from src.infrastructure.composition.factories.micromarket_loading import (
    MasterDataMachineKindLookup,
    build_micromarket_assembly_order_store,
    build_supply_order_category_facts_snapshot_store,
)
from src.infrastructure.field_forms import (
    CoffeeFieldFormLoadingLinkProvider,
    CoffeeFieldFormRevisionLinkProvider,
    coffee_field_form_issue_enabled,
)
from src.infrastructure.integrations.google.forms import (
    GoogleFormsLoadingFormLinkProvider,
    GoogleFormsRevisionFormLinkProvider,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository
from src.infrastructure.micromarket_loading.ms_warehouse_stock import MoySkladWarehouseStockFetcher
from src.infrastructure.micromarket_loading.supply_order_category_sync_worker import (
    SupplyOrderCategoryFactsSyncWorker,
)
from src.infrastructure.micromarket_loading.warehouse_stock_sync_worker import (
    MicromarketWarehouseStockSyncWorker,
)
from src.infrastructure.micromarket_loading_alert_worker import MicromarketLoadingAlertWorker
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.micromarket_loading_orders import (
    MongoMicromarketLoadingOrderStore,
)
from src.infrastructure.moysklad.supply_order_category_reader import (
    MoySkladSupplyOrderCategoryReader,
)
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


class _InMemoryMicromarketLoadingCycleStore:
    def __init__(self) -> None:
        self._cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self._cycles.get(machine_code)

    def list_cycles(self) -> tuple[MicromarketLoadingCycle, ...]:
        return tuple(self._cycles.values())

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        pending = cycle.pull_events()
        del pending
        self._cycles[cycle.machine_code] = cycle


def _build_micromarket_loading_order_store(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
) -> _InMemoryMicromarketLoadingCycleStore | MongoMicromarketLoadingOrderStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_loading_order_events_collection,
            owner="MongoMicromarketLoadingOrderStore",
            client=mongo_client,
        )
        return MongoMicromarketLoadingOrderStore(collection)
    return _InMemoryMicromarketLoadingCycleStore()


@beartype
def wire_machine_ops(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    publisher: OutboxDomainEventPublisher,
    provider: ReferenceDataProvider,
    include_moysklad_http: bool = True,
) -> MachineOpsBundle:
    google_forms = settings.google_forms
    event_store = build_event_store(settings, client=mongo_client)
    service_calendar_timezone = settings.service_calendar.zone_info()
    repository = EventSourcedMachineOperationsRepository(
        event_store=event_store,
        revision_interval_min_days=settings.service_rules.revision_interval_min_days,
        revision_interval_max_days=settings.service_rules.revision_interval_max_days,
        service_calendar_timezone=service_calendar_timezone,
        service_day_end_hour=settings.service_calendar.service_day_end_hour,
    )

    field_forms_base = settings.micromarket_loading.field_forms_public_base_url
    revision_form_links: RevisionFormLinkProvider
    loading_form_links: LoadingFormLinkProvider
    if coffee_field_form_issue_enabled(
        field_forms_public_base_url=field_forms_base,
        revision_form_url=google_forms.revision_form_url,
        loading_form_url=google_forms.loading_form_url,
    ):
        # Cutover gate: FieldForm issue only when Google coffee URLs cleared
        # (prod enable together with ISS-452 — see coffee_field_form_issue_enabled).
        domain_products = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=mongo_client,
        )
        policy_store = build_form_inventory_policy_store(
            settings.mongodb,
            client=mongo_client,
        )
        revision_form_links = CoffeeFieldFormRevisionLinkProvider(
            products=domain_products,
            policies=policy_store,
            token_secret=google_forms.revision_form_token_secret.get_secret_value(),
            field_forms_public_base_url=field_forms_base,
        )
        loading_form_links = CoffeeFieldFormLoadingLinkProvider(
            products=domain_products,
            policies=policy_store,
            token_secret=google_forms.loading_form_token_secret.get_secret_value(),
            field_forms_public_base_url=field_forms_base,
        )
    else:
        revision_form_links = GoogleFormsRevisionFormLinkProvider(
            form_url=google_forms.revision_form_url,
            token_entry_id=google_forms.revision_form_token_entry_id,
            token_secret=google_forms.revision_form_token_secret.get_secret_value(),
        )
        loading_form_links = GoogleFormsLoadingFormLinkProvider(
            form_url=google_forms.loading_form_url,
            token_entry_id=google_forms.loading_form_token_entry_id,
            token_secret=google_forms.loading_form_token_secret.get_secret_value(),
        )
    vending_machines = build_vending_machine_repository(provider)
    technician_last_maintenance = build_technician_last_maintenance_projection(
        settings,
        client=mongo_client,
    )
    bypass = build_maintenance_cooldown_bypass_reader(settings, client=mongo_client)
    executor = MachineOperationsExecutor(
        repository=repository,
        publisher=publisher,
        technician_last_maintenance=technician_last_maintenance,
    )
    cooldown_minutes = settings.service_rules.maintenance_cooldown_minutes
    additional_maintenance: AdditionalMaintenanceAllowed
    if settings.mongodb.is_configured:
        additional_maintenance = ClosableExtraAdditionalMaintenance(
            build_service_visit_store(settings, client=mongo_client),
        )
    else:
        additional_maintenance = AlwaysDenyAdditionalMaintenance()
    master_stores = build_master_data_stores(settings, mongo_client=mongo_client)
    micromarket_loading_cycle_store = _build_micromarket_loading_order_store(
        settings,
        mongo_client=mongo_client,
    )
    inventory_gate = MicromarketCompleteMaintenanceInventoryGate(
        kind_lookup=MasterDataMachineKindLookup(_machines=master_stores.machines),
        stock_store=build_micromarket_device_stock_store(settings, client=mongo_client),
        timezone=service_calendar_timezone,
        day_end_hour=settings.service_calendar.service_day_end_hour,
        order_store=micromarket_loading_cycle_store,
    )
    micromarket_assembly_order_store = build_micromarket_assembly_order_store(
        settings,
        client=mongo_client,
    )
    loading_alerter = build_micromarket_loading_alerter(settings)
    machine_names = VendingMachineNameLookup(vending_machines)
    micromarket_loading_alert_worker = MicromarketLoadingAlertWorker(
        sweep=SweepMicromarketLoadingAlerts(
            cycle_store=micromarket_loading_cycle_store,
            alerter=loading_alerter,
            names=machine_names,
            timezone=service_calendar_timezone,
            day_end_hour=settings.service_calendar.service_day_end_hour,
        ),
    )
    micromarket_warehouse_stock_sync_worker: MicromarketWarehouseStockSyncWorker | None = None
    supply_order_category_facts_sync_worker: SupplyOrderCategoryFactsSyncWorker | None = None
    mm_loading = settings.micromarket_loading
    cat_settings = settings.micromarket_supply_order_category
    if (
        include_moysklad_http
        and mm_loading.execute_enabled
        and mm_loading.main_warehouse_id is not None
    ):
        moysklad = build_moysklad_client(settings.moysklad)
        if moysklad is not None:
            snapshot_store = build_micromarket_warehouse_stock_snapshot_store(
                settings,
                client=mongo_client,
            )
            micromarket_warehouse_stock_sync_worker = MicromarketWarehouseStockSyncWorker(
                sync=SyncMicromarketWarehouseStock(
                    snapshot_store=snapshot_store,
                    planograms=build_micromarket_planogram_store(
                        settings,
                        client=mongo_client,
                    ),
                    products=build_domain_product_store(
                        settings.mongodb,
                        settings.domain_product_identity,
                        client=mongo_client,
                    ),
                    warehouse_id=mm_loading.main_warehouse_id,
                    fetcher=MoySkladWarehouseStockFetcher(
                        client=moysklad,
                        main_warehouse_id=mm_loading.main_warehouse_id,
                    ),
                ),
                snapshot_store=snapshot_store,
                interval_seconds=mm_loading.warehouse_stock_sync_interval_seconds,
                staleness_alert_seconds=mm_loading.warehouse_stock_staleness_alert_seconds,
                staleness_alert_cooldown_seconds=(
                    mm_loading.warehouse_stock_staleness_alert_cooldown_seconds
                ),
                sync_failure_backoff_seconds=(
                    mm_loading.warehouse_stock_sync_failure_backoff_seconds
                ),
                alerter=build_micromarket_warehouse_stock_staleness_alerter(settings),
            )
    if include_moysklad_http:
        try:
            category_reader = MoySkladSupplyOrderCategoryReader.from_settings(
                settings.moysklad,
                attr_shelf_life_days_id=str(cat_settings.attr_shelf_life_days_id),
            )
        except ValueError:
            category_reader = None
        if category_reader is not None:
            category_snapshot_store = build_supply_order_category_facts_snapshot_store(
                settings,
                client=mongo_client,
            )
            supply_order_category_facts_sync_worker = SupplyOrderCategoryFactsSyncWorker(
                sync=SyncSupplyOrderCategoryFacts(
                    snapshot_store=category_snapshot_store,
                    planograms=build_micromarket_planogram_store(
                        settings,
                        client=mongo_client,
                    ),
                    products=build_domain_product_store(
                        settings.mongodb,
                        settings.domain_product_identity,
                        client=mongo_client,
                    ),
                    facts_fetcher=category_reader,
                    folder_index=category_reader,
                ),
                interval_seconds=cat_settings.sync_interval_seconds,
            )
    return MachineOpsBundle(
        event_store=event_store,
        repository=repository,
        executor=executor,
        technician_last_maintenance=technician_last_maintenance,
        vending_machines=vending_machines,
        revision_form_links=revision_form_links,
        loading_form_links=loading_form_links,
        list_available_machines=ListAvailableMachinesService(
            repository=vending_machines,
        ),
        get_service_capabilities=GetServiceCapabilitiesService(
            machine_operations=repository,
            revision_form_links=revision_form_links,
            last_maintenance_reader=technician_last_maintenance,
            maintenance_cooldown_minutes=cooldown_minutes,
            bypass_reader=bypass,
            service_calendar_timezone=service_calendar_timezone,
            additional_maintenance=additional_maintenance,
            inventory_gate=inventory_gate,
        ),
        get_technician_revision_outlook=GetTechnicianRevisionOutlookService(
            machine_operations=repository,
            vending_machines=vending_machines,
        ),
        complete_maintenance=CompleteMaintenanceService(
            executor=executor,
            last_maintenance_reader=technician_last_maintenance,
            maintenance_cooldown_minutes=cooldown_minutes,
            bypass_reader=bypass,
            service_calendar_timezone=service_calendar_timezone,
            additional_maintenance=additional_maintenance,
            inventory_gate=inventory_gate,
        ),
        create_loading_form=CreateLoadingFormService(
            form_links=loading_form_links,
        ),
        maintenance_cooldown_bypass=bypass,
        service_calendar_timezone=service_calendar_timezone,
        maintenance_cooldown_minutes=cooldown_minutes,
        inventory_gate=inventory_gate,
        micromarket_loading_cycle_store=micromarket_loading_cycle_store,
        micromarket_assembly_order_store=micromarket_assembly_order_store,
        micromarket_loading_alert_worker=micromarket_loading_alert_worker,
        micromarket_warehouse_stock_sync_worker=micromarket_warehouse_stock_sync_worker,
        supply_order_category_facts_sync_worker=supply_order_category_facts_sync_worker,
    )
