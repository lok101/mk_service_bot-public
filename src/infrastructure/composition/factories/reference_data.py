from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_submissions.ports import ProductCodeResolver, TelegramUserResolver
from src.application.machine_operations.ports import VendingMachineRepository
from src.application.reference_data import (
    ReferenceDataProvider,
    ReferenceDataSnapshotStore,
    ReferenceDataSourceId,
    SyncReferenceData,
)
from src.application.reference_data.migrate_coffee_locations import (
    migrate_technician_locations_to_coffee,
)
from src.application.reference_data.migrate_product_vitrine import (
    migrate_sheets_product_catalog_to_vitrine,
)
from src.application.reference_data.ports import ProductCatalogDrinkSource
from src.application.reference_data.sync_product_catalog_ms import SyncProductCatalogFromMs
from src.application.sheets.ports import ProductSpecByCodeResolver
from src.config.google_sheets import GoogleSheetsSettings
from src.config.product_catalog_ms import ProductCatalogMsSettings
from src.config.settings import Settings
from src.infrastructure.integrations.google.sheets import (
    GoogleSheetsProductCatalogSource,
    GoogleSheetsProductCodeResolver,
    GoogleSheetsProductSpecByCodeResolver,
    GoogleSheetsTelegramUserResolver,
    GoogleSheetsVendingMachineRepository,
)
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)
from src.infrastructure.reference_data.mongo_store import (
    MongoReferenceDataSnapshotStore,
)
from src.infrastructure.reference_data.ms_assortment_reader import (
    MoySkladProductCatalogAssortmentReader,
    ProductCatalogMsEntityListClient,
)
from src.infrastructure.reference_data.product_catalog_ms_worker import (
    ProductCatalogMsSyncWorker,
)
from src.infrastructure.reference_data.sheets_source_reader import (
    SheetsReferenceDataSourceReader,
)
from src.infrastructure.reference_data.worker import ReferenceDataSyncWorker


@beartype
def build_google_sheets_product_catalog_source(
    provider: ReferenceDataProvider,
) -> GoogleSheetsProductCatalogSource:
    return GoogleSheetsProductCatalogSource(provider=provider)


@beartype
def build_product_code_resolver(
    provider: ReferenceDataProvider,
    *,
    catalog_source: GoogleSheetsProductCatalogSource | None = None,
) -> ProductCodeResolver:
    source = catalog_source or GoogleSheetsProductCatalogSource(provider=provider)
    return GoogleSheetsProductCodeResolver(catalog_source=source)


@beartype
def build_product_spec_by_code_resolver(
    provider: ReferenceDataProvider,
    *,
    catalog_source: GoogleSheetsProductCatalogSource | None = None,
) -> ProductSpecByCodeResolver:
    source = catalog_source or GoogleSheetsProductCatalogSource(provider=provider)
    return GoogleSheetsProductSpecByCodeResolver(catalog_source=source)


@beartype
def build_vending_machine_repository(
    provider: ReferenceDataProvider,
) -> VendingMachineRepository:
    return GoogleSheetsVendingMachineRepository(provider=provider)


@beartype
def build_telegram_user_resolver(
    provider: ReferenceDataProvider,
) -> TelegramUserResolver:
    return GoogleSheetsTelegramUserResolver(provider=provider)


@beartype
def build_reference_data_snapshot_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ReferenceDataSnapshotStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoReferenceDataSnapshotStore.from_settings(mongo, client=client)
    return InMemoryReferenceDataSnapshotStore()


@beartype
def build_reference_data_source_map(
    settings: GoogleSheetsSettings,
    *,
    master_data_enabled: bool = False,
    master_data_users_enabled: bool = False,
    master_data_technicians_enabled: bool = False,
) -> dict[ReferenceDataSourceId, tuple[str, int]]:
    sources: dict[ReferenceDataSourceId, tuple[str, int]] = {}
    if settings.is_coffee_technician_locations_configured:
        assert settings.coffee_technician_locations_sheet_id is not None
        assert settings.users_sheet_id is not None
        spreadsheet = settings.coffee_technician_locations_spreadsheet_id.strip()
        if not master_data_enabled:
            sources[ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS] = (
                spreadsheet,
                settings.coffee_technician_locations_sheet_id,
            )
        if not master_data_users_enabled:
            sources[ReferenceDataSourceId.BOT_USERS] = (
                spreadsheet,
                settings.users_sheet_id,
            )
    if settings.is_snack_technician_locations_configured and not master_data_enabled:
        assert settings.snack_technician_locations_sheet_id is not None
        sources[ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS] = (
            settings.snack_technician_locations_spreadsheet_id.strip(),
            settings.snack_technician_locations_sheet_id,
        )
    if settings.is_product_catalog_configured:
        assert settings.product_catalog_sheet_id is not None
        sources[ReferenceDataSourceId.PRODUCT_VITRINE] = (
            settings.product_catalog_spreadsheet_id.strip(),
            settings.product_catalog_sheet_id,
        )
    if settings.is_technicians_directory_configured and not master_data_technicians_enabled:
        assert settings.technicians_directory_sheet_id is not None
        sources[ReferenceDataSourceId.TECHNICIANS_DIRECTORY] = (
            settings.technicians_directory_spreadsheet_id.strip(),
            settings.technicians_directory_sheet_id,
        )
    if settings.is_locations_directory_configured and not master_data_enabled:
        assert settings.locations_directory_sheet_id is not None
        sources[ReferenceDataSourceId.LOCATIONS_DIRECTORY] = (
            settings.locations_directory_spreadsheet_id.strip(),
            settings.locations_directory_sheet_id,
        )
    return sources


@beartype
def build_reference_data_source_reader(
    settings: GoogleSheetsSettings,
    *,
    master_data_enabled: bool = False,
    master_data_users_enabled: bool = False,
    master_data_technicians_enabled: bool = False,
) -> SheetsReferenceDataSourceReader:
    return SheetsReferenceDataSourceReader(
        credentials_file=settings.credentials_file.strip(),
        sources=build_reference_data_source_map(
            settings,
            master_data_enabled=master_data_enabled,
            master_data_users_enabled=master_data_users_enabled,
            master_data_technicians_enabled=master_data_technicians_enabled,
        ),
    )


@beartype
def build_reference_data_sync(
    settings: Settings,
    *,
    store: ReferenceDataSnapshotStore,
    provider: ReferenceDataProvider,
) -> SyncReferenceData:
    master_data_enabled = settings.master_data.enabled
    master_data_users_enabled = settings.master_data.users_enabled
    master_data_technicians_enabled = settings.master_data.technicians_enabled
    reader = build_reference_data_source_reader(
        settings.google_sheets,
        master_data_enabled=master_data_enabled,
        master_data_users_enabled=master_data_users_enabled,
        master_data_technicians_enabled=master_data_technicians_enabled,
    )
    return SyncReferenceData(
        reader=reader,
        store=store,
        provider=provider,
        source_ids=tuple(
            build_reference_data_source_map(
                settings.google_sheets,
                master_data_enabled=master_data_enabled,
                master_data_users_enabled=master_data_users_enabled,
                master_data_technicians_enabled=master_data_technicians_enabled,
            ).keys()
        ),
    )


@beartype
def build_reference_data_worker(
    settings: Settings,
    *,
    sync: SyncReferenceData,
    store: ReferenceDataSnapshotStore,
) -> ReferenceDataSyncWorker:
    reference_data = settings.reference_data
    return ReferenceDataSyncWorker(
        sync=sync,
        store=store,
        sync_interval_seconds=reference_data.sync_interval_seconds,
        staleness_alert_seconds=reference_data.staleness_alert_seconds,
    )


@beartype
def build_product_catalog_ms_worker(
    *,
    product_catalog_ms: ProductCatalogMsSettings,
    moysklad_client: ProductCatalogMsEntityListClient | None,
    store: ReferenceDataSnapshotStore,
    provider: ReferenceDataProvider,
    drink_source: ProductCatalogDrinkSource,
) -> ProductCatalogMsSyncWorker | None:
    if not product_catalog_ms.sync_enabled or moysklad_client is None:
        return None
    reader = MoySkladProductCatalogAssortmentReader(moysklad_client)
    sync = SyncProductCatalogFromMs(
        reader=reader,
        store=store,
        provider=provider,
        product_folder_ids=product_catalog_ms.product_folder_ids,
        drink_source=drink_source,
    )
    return ProductCatalogMsSyncWorker(
        sync=sync,
        interval_seconds=product_catalog_ms.sync_interval_seconds,
    )


@beartype
def warm_up_reference_data_provider(
    *,
    provider: ReferenceDataProvider,
    store: ReferenceDataSnapshotStore,
    sync: SyncReferenceData,
    master_data_users_enabled: bool = False,
) -> None:
    migrate_sheets_product_catalog_to_vitrine(store)
    migrate_technician_locations_to_coffee(store)
    skip_hydrate = (
        frozenset({ReferenceDataSourceId.BOT_USERS}) if master_data_users_enabled else frozenset()
    )
    provider.hydrate_from_store(store, skip_source_ids=skip_hydrate)
    if all(provider.has_source(source_id) for source_id in sync.source_ids):
        return
    sync.sync_all()
