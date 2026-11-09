from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data import (
    InMemorySystemUserStore,
    SystemUserStore,
    hydrate_provider_from_system_users,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.system_users import MongoSystemUserStore


@beartype
def build_system_user_store(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> SystemUserStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        if mongo_client is None:
            raise ValueError(
                "MONGODB_URI is set but mongo_client is None; refusing in-memory SystemUserStore",
            )
        return MongoSystemUserStore.from_settings(
            mongo,
            settings.master_data,
            client=mongo_client,
        )
    return InMemorySystemUserStore()


@beartype
def grant_planogram_panel_if_mongo(store: SystemUserStore) -> None:
    if isinstance(store, MongoSystemUserStore):
        store.grant_planogram_panel_once()


@beartype
def attach_system_users(
    provider: ReferenceDataProvider,
    *,
    store: SystemUserStore,
    enabled: bool,
) -> None:
    if not enabled:
        return
    hydrate_provider_from_system_users(provider, store)
