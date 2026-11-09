from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.micromarket_loading.ports import MicromarketDeviceStockStore
from src.config.mongodb import MongoSettings
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError
from src.domain.micromarket_loading.events import MicromarketStockEvent
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.micromarket_stock_serialization import (
    micromarket_stock_event_from_document,
    micromarket_stock_event_to_document,
)


@runtime_checkable
class MicromarketStockEventsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketDeviceStockStore(MicromarketDeviceStockStore):
    _collection: MicromarketStockEventsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: MicromarketStockEventsCollection,
    ) -> MongoMicromarketDeviceStockStore:
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
    ) -> MongoMicromarketDeviceStockStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.micromarket_stock_events_collection,
            owner="MongoMicromarketDeviceStockStore",
            client=client,
        )
        return cls.from_collection(cast(MicromarketStockEventsCollection, collection))

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("machine_code", ASCENDING), ("stream_version", ASCENDING)],
            unique=True,
            name="micromarket_stock_stream_version_unique",
        )
        self._collection.create_index(
            "event_id",
            unique=True,
            name="micromarket_stock_event_id_unique",
        )

    @beartype
    def load(self, machine_code: str) -> MicromarketDeviceStock | None:
        events = self.list_events(machine_code)
        if not events:
            return None
        return MicromarketDeviceStock.rehydrate(machine_code=machine_code, events=events)

    @beartype
    def list_events(self, machine_code: str) -> tuple[MicromarketStockEvent, ...]:
        cursor = self._collection.find(
            {"machine_code": machine_code},
            sort=[("stream_version", ASCENDING)],
        )
        return tuple(micromarket_stock_event_from_document(document) for document in cursor)

    @beartype
    def save(self, stock: MicromarketDeviceStock) -> None:
        existing = self._collection.find(
            {"machine_code": stock.machine_code},
            sort=[("stream_version", ASCENDING)],
        )
        current = sum(1 for _ in existing)
        if current != stock.loaded_version:
            raise MicromarketStockConcurrencyError(machine_code=stock.machine_code)

        pending = stock.pull_events()
        if not pending:
            return

        next_version = current
        for event in pending:
            next_version += 1
            try:
                self._collection.insert_one(
                    micromarket_stock_event_to_document(event, stream_version=next_version),
                )
            except DuplicateKeyError as error:
                raise MicromarketStockConcurrencyError(
                    machine_code=stock.machine_code,
                ) from error
