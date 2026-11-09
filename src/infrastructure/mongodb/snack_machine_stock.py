from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.snack_loading.ports import SnackMachineStockStore
from src.config.mongodb import MongoSettings
from src.domain.snack_loading import SnackMachineStock, SnackStockConcurrencyError
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.snack_machine_stock_serialization import (
    snack_stock_event_from_document,
    snack_stock_event_to_document,
)


@runtime_checkable
class SnackMachineStockEventsCollection(Protocol):
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
class MongoSnackMachineStockStore(SnackMachineStockStore):
    _collection: SnackMachineStockEventsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SnackMachineStockEventsCollection,
    ) -> MongoSnackMachineStockStore:
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
    ) -> MongoSnackMachineStockStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.snack_machine_stock_events_collection,
            owner="MongoSnackMachineStockStore",
            client=client,
        )
        return cls.from_collection(cast(SnackMachineStockEventsCollection, collection))

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("machine_code", ASCENDING), ("stream_version", ASCENDING)],
            unique=True,
            name="snack_machine_stock_stream_version_unique",
        )
        self._collection.create_index(
            "event_id",
            unique=True,
            name="snack_machine_stock_event_id_unique",
        )

    @beartype
    def load(self, machine_code: str) -> SnackMachineStock | None:
        cursor = self._collection.find(
            {"machine_code": machine_code},
            sort=[("stream_version", ASCENDING)],
        )
        events = tuple(snack_stock_event_from_document(document) for document in cursor)
        if not events:
            return None
        return SnackMachineStock.rehydrate(machine_code=machine_code, events=events)

    @beartype
    def save(self, stock: SnackMachineStock) -> None:
        existing = self._collection.find(
            {"machine_code": stock.machine_code},
            sort=[("stream_version", ASCENDING)],
        )
        current = sum(1 for _ in existing)
        if current != stock.loaded_version:
            raise SnackStockConcurrencyError(machine_code=stock.machine_code)

        pending = stock.pull_events()
        if not pending:
            return

        next_version = current
        for event in pending:
            next_version += 1
            try:
                self._collection.insert_one(
                    snack_stock_event_to_document(event, stream_version=next_version),
                )
            except DuplicateKeyError as error:
                raise SnackStockConcurrencyError(machine_code=stock.machine_code) from error
