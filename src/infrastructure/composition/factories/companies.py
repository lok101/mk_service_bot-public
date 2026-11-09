from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data import CompanyStore, InMemoryCompanyStore
from src.config.settings import Settings
from src.infrastructure.mongodb.companies import MongoCompanyStore
from src.infrastructure.mongodb.connection import MongoDatabaseSource


@beartype
def build_company_store(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> CompanyStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        if mongo_client is None:
            raise ValueError(
                "MONGODB_URI is set but mongo_client is None; refusing in-memory CompanyStore",
            )
        return MongoCompanyStore.from_settings(
            mongo,
            settings.master_data,
            client=mongo_client,
        )
    return InMemoryCompanyStore()
