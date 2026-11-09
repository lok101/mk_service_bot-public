from __future__ import annotations

from datetime import datetime
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.reference_data import (
    ImportLocationRosterFromSheets,
    LocationRosterDraftStore,
    LocationRosterStore,
    ReferenceDataProvider,
    ReferenceDataSnapshotStore,
    ReferenceDataSourceId,
)
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.sheets import list_all_machines_from_snapshot
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.location_roster import MongoLocationRosterStore
from src.infrastructure.mongodb.location_roster_draft import MongoLocationRosterDraftStore


@beartype
def build_location_roster_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> LocationRosterStore:
    mongo = settings.mongodb
    if mongo.is_configured and client is not None:
        return MongoLocationRosterStore.from_settings(
            mongo,
            settings.location_roster,
            client=client,
        )
    return InMemoryLocationRosterStore()


@beartype
def build_location_roster_draft_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> LocationRosterDraftStore:
    mongo = settings.mongodb
    if mongo.is_configured and client is not None:
        return MongoLocationRosterDraftStore.from_settings(
            mongo,
            settings.location_roster,
            client=client,
        )
    return InMemoryLocationRosterDraftStore()


@beartype
def attach_location_roster(
    provider: ReferenceDataProvider,
    settings: Settings,
    *,
    roster_store: LocationRosterStore,
    snapshot_store: ReferenceDataSnapshotStore,
    now: datetime,
) -> None:
    enabled = settings.location_roster.enabled
    provider.configure_roster(enabled=enabled, store=roster_store if enabled else None)
    if not enabled:
        return
    coffee = snapshot_store.get(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
    snack = snapshot_store.get(ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS)
    catalog = provider.locations_catalog_or_none()
    count = 0 if catalog is None else len(list_all_machines_from_snapshot(catalog))
    ImportLocationRosterFromSheets(store=roster_store).execute(
        coffee_rows=[list(row) for row in coffee.rows] if coffee is not None else [],
        snack_rows=[list(row) for row in snack.rows] if snack is not None else None,
        catalog_machine_count=count,
        now=now,
    )
