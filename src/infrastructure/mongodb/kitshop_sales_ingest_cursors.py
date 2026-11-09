from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection

_CURSOR_ID = "kitshop_sales"


@runtime_checkable
class KitShopSalesIngestCursorCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> object: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
class MongoKitShopSalesIngestCursorStore:
    def __init__(self, collection: KitShopSalesIngestCursorCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: KitShopSalesIngestCursorCollection,
    ) -> MongoKitShopSalesIngestCursorStore:
        return cls(collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoKitShopSalesIngestCursorStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.kitshop_sales_ingest_cursors_collection,
            owner="MongoKitShopSalesIngestCursorStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def load(self) -> datetime | None:
        document = self._collection.find_one({"_id": _CURSOR_ID})
        if document is None:
            return None
        watermark = document.get("watermark")
        if not isinstance(watermark, datetime):
            raise ValueError("kitshop sales ingest cursor watermark must be a datetime")
        return _as_utc(watermark)

    @beartype
    def save(self, watermark: datetime) -> None:
        self._collection.replace_one(
            {"_id": _CURSOR_ID},
            {"_id": _CURSOR_ID, "watermark": _as_utc(watermark)},
            upsert=True,
        )


__all__ = ["MongoKitShopSalesIngestCursorStore"]
