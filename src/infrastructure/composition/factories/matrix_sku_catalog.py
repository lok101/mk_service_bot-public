from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.matrix_automation.ports import MatrixSkuCatalogStore
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.matrix_sku_catalog import MongoMatrixSkuCatalogStore


@beartype
def build_matrix_sku_catalog_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MatrixSkuCatalogStore:
    if not settings.mongodb.is_configured:
        return InMemoryMatrixSkuCatalogStore()
    return MongoMatrixSkuCatalogStore.from_settings(settings.mongodb, client=client)
