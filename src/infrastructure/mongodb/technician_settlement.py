from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.technician_settlement import TechnicianSettlementConcurrencyError
from src.application.technician_settlement.ports import (
    TechnicianSettlementEventStore,
    TechnicianSettlementRepository,
)
from src.config.mongodb import MongoSettings
from src.domain.ids import TechnicianId
from src.domain.technician_settlement import TechnicianSettlement
from src.domain.technician_settlement.events import SettlementEvent
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError
from src.infrastructure.mongodb.technician_settlement_serialization import (
    TECHNICIAN_SETTLEMENT_AGGREGATE_TYPE,
    settlement_event_from_document,
    settlement_event_to_document,
    technician_id_from_event,
)


@runtime_checkable
class TechnicianSettlementEventsCollection(Protocol):
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

    def delete_many(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianSettlementEventStore(TechnicianSettlementEventStore):
    _collection: TechnicianSettlementEventsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: TechnicianSettlementEventsCollection,
    ) -> MongoTechnicianSettlementEventStore:
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
    ) -> MongoTechnicianSettlementEventStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.technician_settlement_events_collection,
            owner="MongoTechnicianSettlementEventStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("aggregate_id", ASCENDING), ("aggregate_version", ASCENDING)],
            unique=True,
            name="technician_settlement_aggregate_version_unique",
        )
        self._collection.create_index(
            "event_id",
            unique=True,
            name="technician_settlement_event_id_unique",
        )

    @beartype
    def append(self, event: SettlementEvent, *, expected_version: int) -> None:
        if expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        if self._collection.find_one({"event_id": event.event_id.value}) is not None:
            return

        aggregate_id = technician_id_from_event(event).value
        latest = self._collection.find_one(
            {
                "aggregate_id": aggregate_id,
                "aggregate_type": TECHNICIAN_SETTLEMENT_AGGREGATE_TYPE,
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

        document = settlement_event_to_document(
            event,
            aggregate_version=expected_version + 1,
        )
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError as error:
            if self._collection.find_one({"event_id": event.event_id.value}) is not None:
                return
            raise EventStoreConcurrencyError(
                f"Failed to append settlement event for aggregate {aggregate_id!r} "
                f"at expected_version {expected_version}",
            ) from error

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[SettlementEvent]:
        cursor = self._collection.find(
            {
                "aggregate_id": technician_id.value,
                "aggregate_type": TECHNICIAN_SETTLEMENT_AGGREGATE_TYPE,
            },
            sort=[("aggregate_version", ASCENDING)],
        )
        return [settlement_event_from_document(document) for document in cursor]

    @beartype
    def count_all(self) -> int:
        return int(self._collection.count_documents({}))

    @beartype
    def delete_all(self) -> int:
        result = self._collection.delete_many({})
        return int(getattr(result, "deleted_count", 0))


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianSettlementRepository(TechnicianSettlementRepository):
    event_store: TechnicianSettlementEventStore

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianSettlement:
        events = self.event_store.get_events_for_technician(technician_id)
        return TechnicianSettlement.rehydrate(
            technician_id,
            events,
            loaded_version=len(events),
        )

    @beartype
    def save(self, aggregate: TechnicianSettlement) -> None:
        pending = aggregate.collect_events()
        if len(pending) > 1:
            raise ValueError("one event per save boundary")
        if not pending:
            return
        try:
            self.event_store.append(
                pending[0],
                expected_version=aggregate.loaded_version,
            )
        except EventStoreConcurrencyError as error:
            raise TechnicianSettlementConcurrencyError(
                technician_id=aggregate.technician_id,
            ) from error
