from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation.base_margin_store_memory import (
    InMemoryMatrixBaseMarginStore,
)
from src.application.matrix_automation.ports import MatrixBaseMarginStore
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.matrix_base_margin import MongoMatrixBaseMarginStore


@beartype
def build_matrix_base_margin_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MatrixBaseMarginStore:
    if not settings.mongodb.is_configured:
        return InMemoryMatrixBaseMarginStore()
    return MongoMatrixBaseMarginStore.from_settings(settings.mongodb, client=client)
