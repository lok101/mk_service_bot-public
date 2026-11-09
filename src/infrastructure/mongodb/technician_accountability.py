from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.technician_accountability.ports import (
    TechnicianAccountabilityEventStore,
    TechnicianAccountabilityRepository,
)
from src.config.mongodb import MongoSettings
from src.domain.ids import TechnicianId
from src.domain.technician_accountability import TechnicianAccountability
from src.domain.technician_accountability.events import AccountabilityEvent
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.technician_accountability_serialization import (
    TECHNICIAN_ACCOUNTABILITY_AGGREGATE_TYPE,
    accountability_event_from_document,
    accountability_event_to_document,
    technician_id_from_event,
)

_MAX_APPEND_RETRIES = 3


@runtime_checkable
class AccountabilityEventsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
        projection: dict[str, int] | None = None,
    ) -> dict[str, Any] | None: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]],
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianAccountabilityEventStore(TechnicianAccountabilityEventStore):
    _collection: AccountabilityEventsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: AccountabilityEventsCollection,
    ) -> MongoTechnicianAccountabilityEventStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoTechnicianAccountabilityEventStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.technician_accountability_events_collection,
            owner="MongoTechnicianAccountabilityEventStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("aggregate_id", ASCENDING), ("aggregate_version", ASCENDING)],
            unique=True,
            name="accountability_aggregate_version_unique",
        )
        self._collection.create_index(
            "event_id", unique=True, name="accountability_event_id_unique"
        )
        self._collection.create_index(
            [("aggregate_id", ASCENDING), ("occurred_at", ASCENDING)],
            name="accountability_timeline",
        )

    @beartype
    def append(self, event: AccountabilityEvent) -> None:
        if self._collection.find_one({"event_id": event.event_id.value}) is not None:
            return

        aggregate_id = technician_id_from_event(event).value
        for attempt in range(_MAX_APPEND_RETRIES):
            latest = self._collection.find_one(
                {
                    "aggregate_id": aggregate_id,
                    "aggregate_type": TECHNICIAN_ACCOUNTABILITY_AGGREGATE_TYPE,
                },
                sort=[("aggregate_version", -1)],
                projection={"aggregate_version": 1},
            )
            next_version = 1
            if latest is not None:
                version = latest.get("aggregate_version")
                if not isinstance(version, int):
                    raise ValueError("aggregate_version must be an integer")
                next_version = version + 1

            document = accountability_event_to_document(
                event,
                aggregate_version=next_version,
            )
            try:
                self._collection.insert_one(document)
                return
            except DuplicateKeyError:
                if attempt + 1 >= _MAX_APPEND_RETRIES:
                    raise
                continue

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[AccountabilityEvent]:
        cursor = self._collection.find(
            {
                "aggregate_id": technician_id.value,
                "aggregate_type": TECHNICIAN_ACCOUNTABILITY_AGGREGATE_TYPE,
            },
            sort=[("aggregate_version", ASCENDING)],
        )
        return [accountability_event_from_document(document) for document in cursor]


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianAccountabilityRepository(TechnicianAccountabilityRepository):
    event_store: TechnicianAccountabilityEventStore

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianAccountability:
        events = self.event_store.get_events_for_technician(technician_id)
        return TechnicianAccountability.rehydrate(technician_id, events)

    @beartype
    def save(self, aggregate: TechnicianAccountability) -> None:
        for event in aggregate.collect_events():
            self.event_store.append(event)
