from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.machine_operations.ports import EventStore
from src.config.mongodb import MongoSettings
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.machine_operations.events import MaintenanceCompleted, PhotosSubmitted
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.contracts import MACHINE_OPERATIONS_AGGREGATE_TYPE
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError
from src.infrastructure.mongodb.serialization import (
    MAINTENANCE_COMPLETED_EVENT_TYPE,
    PHOTOS_SUBMITTED_EVENT_TYPE,
    document_from_event,
    event_from_bson,
    machine_id_from_event,
)


@runtime_checkable
class MachineEventsCollection(Protocol):
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
        sort: list[tuple[str, int]] | None = None,
    ) -> Iterable[dict[str, Any]]: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoEventStore(EventStore):
    _collection: MachineEventsCollection

    @classmethod
    @beartype
    def from_collection(cls, collection: MachineEventsCollection) -> MongoEventStore:
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
    ) -> MongoEventStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.events_collection,
            owner="MongoEventStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("aggregate_id", ASCENDING), ("aggregate_version", ASCENDING)],
            unique=True,
            name="aggregate_version_unique",
        )
        self._collection.create_index("event_id", unique=True, name="event_id_unique")
        self._collection.create_index(
            [("aggregate_id", ASCENDING), ("occurred_at", ASCENDING)],
            name="aggregate_timeline",
        )
        self._collection.create_index(
            [
                ("aggregate_id", ASCENDING),
                ("event_type", ASCENDING),
                ("payload.completed_at", ASCENDING),
            ],
            name="maintenance_completed_window",
        )
        self._collection.create_index(
            [
                ("aggregate_id", ASCENDING),
                ("event_type", ASCENDING),
                ("payload.maintenance_completed_at", ASCENDING),
            ],
            name="photos_maintenance_completed_window",
        )

    @beartype
    def has_any_events(self) -> bool:
        return self._collection.find_one({}, projection={"_id": 1}) is not None

    @beartype
    def append(self, event: DomainEvent, *, expected_version: int) -> None:
        if expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        if self._collection.find_one({"event_id": event.event_id.value}) is not None:
            return

        aggregate_id = machine_id_from_event(event).value
        latest = self._collection.find_one(
            {
                "aggregate_id": aggregate_id,
                "aggregate_type": MACHINE_OPERATIONS_AGGREGATE_TYPE,
            },
            sort=[("aggregate_version", -1)],
            projection={"aggregate_version": 1},
        )
        current_version = 0
        if latest is not None:
            version = latest.get("aggregate_version")
            if not isinstance(version, int) or version < 1:
                raise ValueError(
                    f"Invalid aggregate_version stored for aggregate {aggregate_id!r}",
                )
            current_version = version
        if expected_version != current_version:
            raise EventStoreConcurrencyError(
                f"Expected version {expected_version} for aggregate {aggregate_id!r}, "
                f"current is {current_version}",
            )

        document = document_from_event(event, aggregate_version=expected_version + 1)
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError as error:
            if self._collection.find_one({"event_id": event.event_id.value}) is not None:
                return
            raise EventStoreConcurrencyError(
                f"Failed to append event for aggregate {aggregate_id!r} "
                f"at expected_version {expected_version}",
            ) from error

    @beartype
    def get_events_for_machine(self, machine_id: MachineId) -> list[DomainEvent]:
        cursor = self._collection.find(
            {
                "aggregate_id": machine_id.value,
                "aggregate_type": MACHINE_OPERATIONS_AGGREGATE_TYPE,
            },
            sort=[("aggregate_version", ASCENDING)],
        )
        return [event_from_bson(document) for document in cursor]

    @beartype
    def list_maintenance_completed_in_completed_at_window(
        self,
        machine_id: MachineId,
        *,
        completed_at_start_inclusive: datetime,
        completed_at_end_exclusive: datetime,
    ) -> tuple[MaintenanceCompleted, ...]:
        cursor = self._collection.find(
            {
                "aggregate_id": machine_id.value,
                "aggregate_type": MACHINE_OPERATIONS_AGGREGATE_TYPE,
                "$or": [
                    {
                        "event_type": MAINTENANCE_COMPLETED_EVENT_TYPE,
                        "payload.completed_at": {
                            "$gte": completed_at_start_inclusive,
                            "$lt": completed_at_end_exclusive,
                        },
                    },
                    {
                        "event_type": PHOTOS_SUBMITTED_EVENT_TYPE,
                        "payload.maintenance_completed_at": {
                            "$gte": completed_at_start_inclusive,
                            "$lt": completed_at_end_exclusive,
                        },
                    },
                ],
            },
        )
        events: list[MaintenanceCompleted] = []
        for document in cursor:
            domain_event = event_from_bson(document)
            if isinstance(domain_event, MaintenanceCompleted):
                events.append(domain_event)
                continue
            if isinstance(domain_event, PhotosSubmitted):
                if domain_event.maintenance_completed_at is None:
                    continue
                events.append(
                    MaintenanceCompleted(
                        event_id=domain_event.event_id,
                        technician_id=domain_event.technician_id,
                        machine_id=domain_event.machine_id,
                        completed_at=domain_event.maintenance_completed_at,
                        occurred_at=domain_event.occurred_at,
                    ),
                )
        events.sort(key=lambda item: (item.completed_at, item.event_id.value))
        return tuple(events)
