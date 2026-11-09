from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class SalesMonitoringWorkerStatusCollection(Protocol):
    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
@dataclass(slots=True)
class MongoSalesMonitoringWorkerStatusRepository:
    collection: SalesMonitoringWorkerStatusCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SalesMonitoringWorkerStatusCollection,
    ) -> MongoSalesMonitoringWorkerStatusRepository:
        return cls(collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoSalesMonitoringWorkerStatusRepository:
        collection = resolve_collection(
            settings,
            collection_name=settings.sales_monitoring_worker_status_collection,
            owner="MongoSalesMonitoringWorkerStatusRepository",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.collection.update_one(
            {"_id": "worker"},
            {"$set": {"last_heartbeat_at": at, "worker_enabled": enabled}},
            upsert=True,
        )
