from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection

_GLOBAL_CURSOR_ID = "global"


@runtime_checkable
class SalesSheetExportCursorCollection(Protocol):
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
@dataclass(frozen=True, slots=True)
class MongoSalesSheetExportCursorStore:
    _collection: SalesSheetExportCursorCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SalesSheetExportCursorCollection,
    ) -> MongoSalesSheetExportCursorStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoSalesSheetExportCursorStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.sales_sheet_export_cursor_collection,
            owner="MongoSalesSheetExportCursorStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def load(self) -> tuple[datetime, str] | None:
        document = self._collection.find_one({"_id": _GLOBAL_CURSOR_ID})
        if document is None:
            return None
        occurred_at = document.get("occurred_at")
        source_id = document.get("source_id")
        if not isinstance(occurred_at, datetime) or not isinstance(source_id, str):
            raise ValueError("sales sheet export cursor has invalid shape")
        return _as_utc(occurred_at), source_id

    @beartype
    def save(self, *, occurred_at: datetime, source_id: str) -> None:
        self._collection.replace_one(
            {"_id": _GLOBAL_CURSOR_ID},
            {
                "_id": _GLOBAL_CURSOR_ID,
                "occurred_at": _as_utc(occurred_at),
                "source_id": source_id,
            },
            upsert=True,
        )
