from __future__ import annotations

from collections.abc import Callable
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data import (
    InMemoryTechnicianStore,
    TechnicianStore,
    hydrate_technicians_directory,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.technicians import MongoTechnicianStore


@beartype
def build_technician_store(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> TechnicianStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        if mongo_client is None:
            raise ValueError(
                "MONGODB_URI is set but mongo_client is None; refusing in-memory TechnicianStore",
            )
        return MongoTechnicianStore.from_settings(
            mongo,
            settings.master_data,
            client=mongo_client,
        )
    return InMemoryTechnicianStore()


@beartype
def attach_technicians(
    provider: ReferenceDataProvider,
    *,
    store: TechnicianStore,
    enabled: bool,
) -> None:
    if not enabled:
        return
    hydrate_technicians_directory(provider, store)


@beartype
def build_technicians_export_hook(
    settings: Settings,
    store: TechnicianStore,
) -> Callable[[], None] | None:
    """Technicians Sheets export disabled (mirror pack); keep signature for call-site quiescence."""
    del settings, store
    return None
