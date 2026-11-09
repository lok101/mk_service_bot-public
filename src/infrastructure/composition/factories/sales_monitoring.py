from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.sales_monitoring.ports import (
    SalesMonitoringAuditStore,
    StatusBoardPointerStore,
)
from src.config.settings import Settings
from src.infrastructure.mongodb.sales_monitoring_audit import MongoSalesMonitoringAuditStore
from src.infrastructure.mongodb.sales_monitoring_status_board import (
    MongoStatusBoardPointerStore,
)
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore
from src.infrastructure.sales_monitoring.memory_status_board import (
    InMemoryStatusBoardPointerStore,
)


@beartype
def build_sales_monitoring_audit_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> SalesMonitoringAuditStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoSalesMonitoringAuditStore.from_settings(mongo, client=client)
    return InMemorySalesMonitoringAuditStore()


@beartype
def build_status_board_pointer_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> StatusBoardPointerStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoStatusBoardPointerStore.from_settings(mongo, client=client)
    return InMemoryStatusBoardPointerStore()
