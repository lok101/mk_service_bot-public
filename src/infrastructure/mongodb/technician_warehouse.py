from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.technician_warehouse import TechnicianWarehouseConcurrencyError
from src.application.technician_warehouse.ports import (
    TechnicianWarehouseEventStore,
    TechnicianWarehouseRepository,
    has_finalized_transfers_for_session_in_events,
)
from src.config.mongodb import MongoSettings
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import WarehouseEvent
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection
from src.infrastructure.mongodb.technician_warehouse_serialization import (
    TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
    warehouse_event_from_document,
    warehouse_event_to_document,
)


@runtime_checkable
class TechnicianWarehouseEventsCollection(Protocol):
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

    def distinct(self, key: str, filter: dict[str, Any], **kwargs: Any) -> list[Any]: ...

    def delete_many(self, filter: dict[str, Any]) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianWarehouseEventStore(TechnicianWarehouseEventStore):
    _collection: TechnicianWarehouseEventsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: TechnicianWarehouseEventsCollection,
    ) -> MongoTechnicianWarehouseEventStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoTechnicianWarehouseEventStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.technician_warehouse_events_collection,
            owner="MongoTechnicianWarehouseEventStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("aggregate_id", ASCENDING), ("aggregate_version", ASCENDING)],
            unique=True,
            name="technician_warehouse_aggregate_version_unique",
        )
        self._collection.create_index(
            "event_id",
            unique=True,
            name="technician_warehouse_event_id_unique",
        )

    @beartype
    def append(
        self,
        technician_id: TechnicianId,
        expected_version: int,
        events: tuple[WarehouseEvent, ...],
    ) -> None:
        """Append events to the technician stream with optimistic concurrency.

        Events in one call are inserted sequentially without a Mongo transaction.
        The domain currently emits one pending event per command, so a partial
        stream mid-batch is not expected. Multi-event batches and atomicity are
        out of scope until such commands exist.
        """
        stream = self.get_events_for_technician(technician_id)
        existing_ids = {event.event_id for event in stream}
        if all(event.event_id in existing_ids for event in events):
            return

        if expected_version != len(stream):
            raise TechnicianWarehouseConcurrencyError(technician_id=technician_id)

        next_version = len(stream)
        for event in events:
            if event.event_id in existing_ids:
                continue
            if event.technician_id != technician_id:
                raise ValueError("event technician_id mismatch")
            next_version += 1
            document = warehouse_event_to_document(event, aggregate_version=next_version)
            try:
                self._collection.insert_one(document)
            except DuplicateKeyError as error:
                if self._collection.find_one({"event_id": event.event_id.value}) is not None:
                    existing_ids.add(event.event_id)
                    continue
                raise TechnicianWarehouseConcurrencyError(
                    technician_id=technician_id,
                ) from error
            existing_ids.add(event.event_id)

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[WarehouseEvent]:
        cursor = self._collection.find(
            {
                "aggregate_id": technician_id.value,
                "aggregate_type": TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
            },
            sort=[("aggregate_version", ASCENDING)],
        )
        return [warehouse_event_from_document(document) for document in cursor]

    @beartype
    def list_technician_ids(self) -> tuple[TechnicianId, ...]:
        raw_ids = self._collection.distinct(
            "aggregate_id",
            {"aggregate_type": TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE},
        )
        return tuple(TechnicianId(str(technician_id)) for technician_id in sorted(raw_ids))

    @beartype
    def delete_all_for_technician(self, technician_id: TechnicianId) -> int:
        result = self._collection.delete_many(
            {
                "aggregate_type": TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
                "aggregate_id": technician_id.value,
            }
        )
        return int(result.deleted_count)


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianWarehouseRepository(TechnicianWarehouseRepository):
    event_store: TechnicianWarehouseEventStore

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse:
        events = self.event_store.get_events_for_technician(technician_id)
        return TechnicianWarehouse.rehydrate(technician_id, events)

    @beartype
    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None:
        pending = warehouse.collect_events()
        if not pending:
            return
        self.event_store.append(
            warehouse.technician_id,
            expected_version,
            pending,
        )
        warehouse.clear_pending_events()

    @beartype
    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        events = self.event_store.get_events_for_technician(technician_id)
        return has_finalized_transfers_for_session_in_events(events, session_id=session_id)
