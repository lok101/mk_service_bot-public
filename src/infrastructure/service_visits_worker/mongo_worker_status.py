from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class ServiceVisitsWorkerStatusCollection(Protocol):
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
class MongoServiceVisitsWorkerStatusRepository:
    collection: ServiceVisitsWorkerStatusCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: ServiceVisitsWorkerStatusCollection,
    ) -> MongoServiceVisitsWorkerStatusRepository:
        return cls(collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        collection_name: str,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoServiceVisitsWorkerStatusRepository:
        collection = resolve_collection(
            settings,
            collection_name=collection_name,
            owner="MongoServiceVisitsWorkerStatusRepository",
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

    @beartype
    def mark_materialized(self, day: date) -> None:
        self.collection.update_one(
            {"_id": "worker"},
            {"$set": {"last_materialized_operational_day": day.isoformat()}},
            upsert=True,
        )

    @property
    @beartype
    def last_materialized_operational_day(self) -> date | None:
        document = self.collection.find_one({"_id": "worker"})
        if document is None:
            return None
        raw = document.get("last_materialized_operational_day")
        if raw is None:
            return None
        return date.fromisoformat(raw)
