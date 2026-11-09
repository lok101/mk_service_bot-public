from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.shared.admin_nav import AdminNavStructureStore
from src.application.shared.admin_nav_memory import InMemoryAdminNavStructureStore
from src.config.settings import Settings
from src.infrastructure.mongodb.admin_nav_structure import MongoAdminNavStructureStore
from src.infrastructure.mongodb.connection import MongoDatabaseSource


@beartype
def build_admin_nav_structure_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> AdminNavStructureStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoAdminNavStructureStore.from_settings(mongo, client=client)
    return InMemoryAdminNavStructureStore()
