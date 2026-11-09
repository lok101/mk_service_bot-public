from __future__ import annotations

from collections.abc import Callable
from typing import Any

from beartype import beartype
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pymongo import MongoClient

from src.application.master_data import (
    CoffeeEquipmentCatalogs,
    InMemoryCoffeeMachineModelStore,
    InMemoryMasterDataStores,
    InMemoryStandColorStore,
    InMemoryStandTypeStore,
    MasterDataExportHook,
    MasterDataStores,
    hydrate_provider_from_master_data,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.config.settings import Settings
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.integrations.google.sheets.sheet_reader import (
    GOOGLE_SHEETS_WRITE_SCOPE,
)
from src.infrastructure.mongodb.coffee_equipment import mongo_coffee_equipment_catalogs
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.master_data import MongoMasterDataStores
from src.infrastructure.reference_data.master_data_sheets_export import (
    GoogleSheetsMasterDataExport,
    MasterDataSheetTarget,
)


@beartype
def build_master_data_stores(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MasterDataStores:
    mongo = settings.mongodb
    if mongo.is_configured and mongo_client is not None:
        return MongoMasterDataStores.from_settings(
            mongo,
            settings.master_data,
            client=mongo_client,
        )
    return InMemoryMasterDataStores()


@beartype
def build_coffee_equipment_stores(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> CoffeeEquipmentCatalogs:
    mongo = settings.mongodb
    if mongo.is_configured:
        if mongo_client is None:
            raise ValueError(
                "MONGODB_URI is set but mongo_client is None; "
                "refusing in-memory coffee equipment catalogs",
            )
        return mongo_coffee_equipment_catalogs(
            mongo,
            settings.master_data,
            client=mongo_client,
        )
    return CoffeeEquipmentCatalogs(
        models=InMemoryCoffeeMachineModelStore(),
        stand_types=InMemoryStandTypeStore(),
        stand_colors=InMemoryStandColorStore(),
    )


@beartype
def attach_master_data(
    provider: ReferenceDataProvider,
    *,
    stores: MasterDataStores,
    enabled: bool,
) -> None:
    if not enabled:
        return
    hydrate_provider_from_master_data(provider, stores)


@beartype
def build_master_data_export_hook(
    settings: Settings,
    *,
    roster_store: LocationRosterStore,
    technician_names: dict[TechnicianId, str],
    company_names_provider: Callable[[MasterDataStores], dict[MachineId, str]],
) -> MasterDataExportHook | None:
    if not settings.master_data.sheets_export_enabled:
        return None
    md = settings.master_data
    locations_sheet_id = md.mirror_locations_sheet_id
    machines_sheet_id = md.mirror_machines_sheet_id
    assert locations_sheet_id is not None
    assert machines_sheet_id is not None
    credentials_file = settings.google_sheets.credentials_file.strip()
    spreadsheet_id = md.mirror_spreadsheet_id.strip()

    def _service() -> Any:
        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            credentials_file,
            scopes=[GOOGLE_SHEETS_WRITE_SCOPE],
        )
        return build("sheets", "v4", credentials=credentials)

    return GoogleSheetsMasterDataExport(
        service_factory=_service,
        locations=MasterDataSheetTarget(
            spreadsheet_id=spreadsheet_id,
            sheet_id=locations_sheet_id,
        ),
        machines=MasterDataSheetTarget(
            spreadsheet_id=spreadsheet_id,
            sheet_id=machines_sheet_id,
        ),
        roster=roster_store,
        technician_names=dict(technician_names),
        company_names_provider=company_names_provider,
    )


from src.application.reference_data.ports import LocationRosterStore  # noqa: E402
