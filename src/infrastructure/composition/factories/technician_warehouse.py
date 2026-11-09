from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_inventory_policy import FormInventoryPolicyStore
from src.application.form_submissions.ports import FormSubmissionStore, ProductCodeResolver
from src.application.machine_operations.ports import TechnicianWarehouseInventoryLinkProvider
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import ReferenceDataProvider
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_warehouse.accept_inventory import (
    AcceptTechnicianWarehouseInventoryService,
)
from src.application.technician_warehouse.backfill_loadings import (
    BackfillTechnicianWarehouseLoadings,
)
from src.application.technician_warehouse.close_warehouse import CloseTechnicianWarehouse
from src.application.technician_warehouse.delta import TechnicianWarehouseDeltaService
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.application.technician_warehouse.ports import (
    BorderProductGate,
    CatalogBaseQuantityResolver,
    DomainEventPublisher,
    ReadMovesResult,
    TechnicianWarehouseEventStore,
    TechnicianWarehouseRepository,
    TechnicianWarehouseTransferReader,
)
from src.application.technician_warehouse.wipe_warehouse import WipeTechnicianWarehouse
from src.config.google_forms import GoogleFormsSettings
from src.config.settings import Settings
from src.domain.technician_warehouse.errors import MoySkladUnavailable
from src.infrastructure.composition.adapters.warehouse_wipe_draft_cleanup import (
    SettlementDraftWipeCleanup,
)
from src.infrastructure.composition.factories.reference_data import (
    build_product_spec_by_code_resolver,
)
from src.infrastructure.integrations.google.forms.link_providers import (
    GoogleFormsTechnicianWarehouseInventoryLinkProvider,
    UnconfiguredTechnicianWarehouseInventoryLinkProvider,
)
from src.infrastructure.integrations.moysklad.client import MoySkladClient
from src.infrastructure.integrations.moysklad.technician_warehouse_transfer_reader import (
    MoySkladTechnicianWarehouseTransferReader,
)
from src.infrastructure.integrations.moysklad.warehouse_move_quantity import (
    MoySkladCatalogBaseQuantityResolver,
)
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.event_store import MachineEventsCollection
from src.infrastructure.mongodb.technician_warehouse import (
    MongoTechnicianWarehouseEventStore,
    MongoTechnicianWarehouseRepository,
    TechnicianWarehouseEventsCollection,
)
from src.infrastructure.mongodb.warehouse_loading_backfill_source import (
    MongoWarehouseLoadingBackfillSource,
)
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)


@beartype
@dataclass(frozen=True, slots=True)
class _UnavailableTechnicianWarehouseTransferReader(TechnicianWarehouseTransferReader):
    async def ensure_supply_store_codes_exist(self, codes: tuple[str, ...]) -> None:
        _ = codes
        raise MoySkladUnavailable("MoySklad is not configured")

    async def read_moves(
        self,
        *,
        technician_store_code: str,
        moment_from: datetime,
        moment_to: datetime,
    ) -> ReadMovesResult:
        _ = technician_store_code, moment_from, moment_to
        raise MoySkladUnavailable("MoySklad is not configured")


@beartype
def build_technician_warehouse_repository(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> tuple[TechnicianWarehouseRepository, TechnicianWarehouseEventStore]:
    mongo = settings.mongodb
    if mongo.is_configured:
        mongo_event_store = MongoTechnicianWarehouseEventStore.from_settings(
            mongo,
            client=client,
        )
        return (
            MongoTechnicianWarehouseRepository(event_store=mongo_event_store),
            mongo_event_store,
        )
    memory_event_store = InMemoryTechnicianWarehouseEventStore()
    return (
        InMemoryTechnicianWarehouseRepository(event_store=memory_event_store),
        memory_event_store,
    )


@beartype
def build_technician_warehouse_executor(
    repository: TechnicianWarehouseRepository,
    publisher: DomainEventPublisher | None = None,
) -> TechnicianWarehouseExecutor:
    return TechnicianWarehouseExecutor(repository=repository, publisher=publisher)


@beartype
def build_technician_warehouse_transfer_reader(
    moysklad_client: MoySkladClient | None,
) -> TechnicianWarehouseTransferReader:
    if moysklad_client is None:
        return _UnavailableTechnicianWarehouseTransferReader()
    return MoySkladTechnicianWarehouseTransferReader(client=moysklad_client)


@beartype
def build_technician_warehouse_catalog_resolver(
    provider: ReferenceDataProvider,
) -> CatalogBaseQuantityResolver:
    return MoySkladCatalogBaseQuantityResolver(
        product_resolver=build_product_spec_by_code_resolver(provider),
    )


@beartype
def build_technician_warehouse_import(
    settings: Settings,
    *,
    reader: TechnicianWarehouseTransferReader,
    resolver: CatalogBaseQuantityResolver,
    executor: TechnicianWarehouseExecutor,
    border_gate: BorderProductGate | None = None,
) -> ImportTechnicianWarehouseTransfers:
    warehouse_settings = settings.technician_warehouse
    return ImportTechnicianWarehouseTransfers(
        reader=reader,
        catalog_base_quantity_resolver=resolver,
        executor=executor,
        supply_store_codes=warehouse_settings.supply_store_codes,
        lookback_days=warehouse_settings.ms_lookback_days,
        border_gate=border_gate,
    )


@beartype
def build_technician_warehouse_delta_port(
    *,
    importer: ImportTechnicianWarehouseTransfers,
    executor: TechnicianWarehouseExecutor,
) -> TechnicianWarehouseDeltaService:
    return TechnicianWarehouseDeltaService(
        importer=importer,
        executor=executor,
    )


@beartype
def build_accept_technician_warehouse_inventory(
    *,
    store: FormSubmissionStore,
    resolver: ProductCodeResolver,
    executor: TechnicianWarehouseExecutor,
    google_forms_settings: GoogleFormsSettings,
) -> AcceptTechnicianWarehouseInventoryService:
    return AcceptTechnicianWarehouseInventoryService(
        form_submission_store=store,
        product_code_resolver=resolver,
        form_token_field_name=google_forms_settings.token_field_name,
        executor=executor,
    )


@beartype
def build_technician_warehouse_inventory_link_provider(
    google_forms_settings: GoogleFormsSettings,
    *,
    field_forms_public_base_url: str = "",
    products: DomainProductStore | None = None,
    policies: FormInventoryPolicyStore | None = None,
) -> TechnicianWarehouseInventoryLinkProvider:
    from src.infrastructure.field_forms.warehouse_link_providers import (
        TechnicianWarehouseInventoryFieldFormLinkProvider,
        technician_warehouse_field_form_issue_enabled,
    )

    google_url = google_forms_settings.technician_warehouse_inventory_form_url
    token_secret = (
        google_forms_settings.technician_warehouse_inventory_form_token_secret.get_secret_value()
    )
    if technician_warehouse_field_form_issue_enabled(
        field_forms_public_base_url=field_forms_public_base_url,
        technician_warehouse_inventory_form_url=google_url,
    ):
        if products is None or policies is None:
            raise ValueError(
                "FieldForm warehouse inventory link requires products and policies",
            )
        return TechnicianWarehouseInventoryFieldFormLinkProvider(
            products=products,
            policies=policies,
            token_secret=token_secret,
            field_forms_public_base_url=field_forms_public_base_url,
            clock=lambda: datetime.now(tz=UTC),
        )
    if not google_url.strip():
        return UnconfiguredTechnicianWarehouseInventoryLinkProvider()
    return GoogleFormsTechnicianWarehouseInventoryLinkProvider(
        form_url=google_url,
        token_entry_id=google_forms_settings.technician_warehouse_inventory_form_token_entry_id,
        token_secret=token_secret,
        clock=lambda: datetime.now(tz=UTC),
    )


@beartype
def build_observe_technician_warehouse_loading(
    executor: TechnicianWarehouseExecutor,
) -> ObserveTechnicianWarehouseLoading:
    return ObserveTechnicianWarehouseLoading(executor=executor)


@beartype
def build_close_technician_warehouse(
    *,
    executor: TechnicianWarehouseExecutor,
    importer: ImportTechnicianWarehouseTransfers,
) -> CloseTechnicianWarehouse:
    return CloseTechnicianWarehouse(executor=executor, importer=importer)


@beartype
def build_backfill_technician_warehouse_loadings(
    *,
    machine_events: MachineEventsCollection,
    warehouse_events: TechnicianWarehouseEventsCollection,
    form_submission_store: FormSubmissionStore,
    observe_loading: ObserveTechnicianWarehouseLoading,
    repository: TechnicianWarehouseRepository,
) -> BackfillTechnicianWarehouseLoadings:
    source = MongoWarehouseLoadingBackfillSource(
        machine_events=machine_events,
        warehouse_events=warehouse_events,
    )
    return BackfillTechnicianWarehouseLoadings(
        source=source,
        form_submission_store=form_submission_store,
        observe_loading=observe_loading,
        repository=repository,
    )


@beartype
def build_wipe_technician_warehouse(
    *,
    event_store: TechnicianWarehouseEventStore,
    repository: TechnicianWarehouseRepository,
    draft_store: ReconciliationDraftStore,
) -> WipeTechnicianWarehouse:
    return WipeTechnicianWarehouse(
        event_store=event_store,
        repository=repository,
        draft_cleanup=SettlementDraftWipeCleanup(draft_store=draft_store),
    )
