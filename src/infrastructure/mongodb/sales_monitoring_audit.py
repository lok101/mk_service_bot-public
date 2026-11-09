from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.sales_monitoring.no_sales_control import control_blocks_technician_visit
from src.config.mongodb import MongoSettings
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
)
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.sales_monitoring_audit_documents import (
    build_audit_document,
    document_from_no_sales_episode,
    document_from_no_sales_episode_opened,
    no_sales_audit_document_id,
    normalize_audit_document,
    offline_audit_document_id,
)

_NO_SALES_CONTROL_KINDS = ("no_sales_mute", "no_sales_mute_cancel", "no_sales_engineer_wait")


@runtime_checkable
class SalesMonitoringAuditCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> object: ...

    def find(self, filter: dict[str, Any]) -> Any: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoSalesMonitoringAuditStore:
    _collection: SalesMonitoringAuditCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SalesMonitoringAuditCollection,
    ) -> MongoSalesMonitoringAuditStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoSalesMonitoringAuditStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.sales_monitoring_audit_collection,
            owner="MongoSalesMonitoringAuditStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def upsert_from_event(self, event: DomainEvent) -> None:
        existing: dict[str, Any] | None = None
        if isinstance(event, SalesMonitoringOfflineCleared):
            existing = self._collection.find_one(
                {"_id": offline_audit_document_id(event.machine_id)},
            )
        elif isinstance(event, SalesMonitoringNoSalesStaleCleared):
            existing = self._collection.find_one(
                {"_id": no_sales_audit_document_id(event.machine_id)},
            )
        document = build_audit_document(event, existing=existing)
        self._collection.replace_one(
            {"_id": document["_id"]},
            document,
            upsert=True,
        )
        if isinstance(event, SalesMonitoringNoSalesStaleOpened):
            episode = document_from_no_sales_episode_opened(event)
            existing_episode = self._collection.find_one({"_id": episode["_id"]})
            if existing_episode is not None and existing_episode.get("cleared_at") is not None:
                return
            self._collection.replace_one(
                {"_id": episode["_id"]},
                episode,
                upsert=True,
            )
        elif isinstance(event, SalesMonitoringNoSalesStaleCleared):
            episode = document_from_no_sales_episode(event)
            self._collection.replace_one(
                {"_id": episode["_id"]},
                episode,
                upsert=True,
            )

    @beartype
    def upsert_control(self, document: dict[str, object]) -> None:
        self._collection.replace_one(
            {"_id": document["_id"]},
            dict(document),
            upsert=True,
        )

    @beartype
    def upsert_audit_document(self, document: dict[str, object]) -> None:
        """Upsert any audit document by `_id` without sticky/episode event side effects."""
        self._collection.replace_one(
            {"_id": document["_id"]},
            dict(document),
            upsert=True,
        )

    @beartype
    def list_no_sales_controls(self, machine_id: MachineId) -> list[dict[str, object]]:
        return [
            normalize_audit_document(document)
            for document in self._collection.find(
                {
                    "machine_id": machine_id.value,
                    "kind": {"$in": list(_NO_SALES_CONTROL_KINDS)},
                }
            )
        ]

    @beartype
    def blocks_technician_visit(self, *, machine_id: MachineId, opened_event_id: str) -> bool:
        return control_blocks_technician_visit(
            self.list_no_sales_controls(machine_id),
            machine_id=machine_id,
            opened_event_id=opened_event_id,
        )

    @beartype
    def list_open_offline(self) -> list[dict[str, object]]:
        return [
            normalize_audit_document(document)
            for document in self._collection.find({"kind": "offline", "status": "open"})
        ]

    @beartype
    def list_open_no_sales(self) -> list[dict[str, object]]:
        return [
            normalize_audit_document(document)
            for document in self._collection.find({"kind": "no_sales", "status": "open"})
        ]

    @beartype
    def list_cleared_no_sales_since(self, *, cleared_at_gte: datetime) -> list[dict[str, object]]:
        return [
            normalize_audit_document(document)
            for document in self._collection.find(
                {
                    "kind": "no_sales",
                    "status": "cleared",
                    "cleared_at": {"$gte": cleared_at_gte},
                }
            )
        ]

    @beartype
    def list_no_sales_episodes_overlapping(
        self, *, start: datetime, end: datetime
    ) -> list[dict[str, object]]:
        return [
            normalize_audit_document(document)
            for document in self._collection.find(
                {
                    "kind": "no_sales_episode",
                    "$or": [
                        {"opened_at": {"$gte": start, "$lte": end}},
                        {"cleared_at": {"$gte": start, "$lte": end}},
                    ],
                }
            )
        ]

    @beartype
    def get(self, document_id: str) -> dict[str, object] | None:
        document = self._collection.find_one({"_id": document_id})
        return normalize_audit_document(document) if document is not None else None
