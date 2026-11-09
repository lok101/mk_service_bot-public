from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, DESCENDING, MongoClient

from src.config.mongodb import MongoSettings
from src.domain.machine_sales import MachineSale
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.mongodb.machine_sales import machine_sale_from_document


@runtime_checkable
class SalesForSheetExportCollection(Protocol):
    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
@dataclass(frozen=True, slots=True)
class MongoSalesForSheetExportLoader:
    collection: SalesForSheetExportCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SalesForSheetExportCollection,
    ) -> MongoSalesForSheetExportLoader:
        loader = cls(collection=collection)
        loader.ensure_indexes()
        return loader

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoSalesForSheetExportLoader:
        collection = resolve_collection(
            settings,
            collection_name=settings.machine_sales_collection,
            owner="MongoSalesForSheetExportLoader",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("occurred_at", ASCENDING), ("source_id", ASCENDING)],
            name="machine_sales_occurred_at_source_id",
        )

    @beartype
    def list_latest(self, *, limit: int) -> Sequence[MachineSale]:
        cursor = self.collection.find(
            {},
            sort=[("occurred_at", DESCENDING), ("source_id", DESCENDING)],
        ).limit(limit)
        documents = list(cursor)
        documents.reverse()
        return tuple(machine_sale_from_document(document) for document in documents)

    @beartype
    def list_after(
        self,
        *,
        occurred_at: datetime,
        source_id: str,
        limit: int,
    ) -> Sequence[MachineSale]:
        occurred_at_utc = _as_utc(occurred_at)
        cursor = self.collection.find(
            {
                "$or": [
                    {"occurred_at": {"$gt": occurred_at_utc}},
                    {
                        "occurred_at": occurred_at_utc,
                        "source_id": {"$gt": source_id},
                    },
                ],
            },
            sort=[("occurred_at", ASCENDING), ("source_id", ASCENDING)],
        ).limit(limit)
        return tuple(machine_sale_from_document(document) for document in cursor)
