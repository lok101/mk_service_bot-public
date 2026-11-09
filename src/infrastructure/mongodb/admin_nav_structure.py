from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.shared.admin_nav import (
    AdminNavStructure,
    admin_nav_structure_to_raw,
    parse_admin_nav_structure,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_DEFAULT_DOC_ID = "default"


@runtime_checkable
class AdminNavStructureCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
@dataclass(frozen=True, slots=True)
class MongoAdminNavStructureStore:
    _collection: AdminNavStructureCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: AdminNavStructureCollection,
    ) -> MongoAdminNavStructureStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoAdminNavStructureStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.admin_nav_structure_collection,
            owner="MongoAdminNavStructureStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def get(self) -> AdminNavStructure | None:
        document = self._collection.find_one({"_id": _DEFAULT_DOC_ID})
        if document is None:
            return None
        return parse_admin_nav_structure(document.get("nodes"))

    @beartype
    def save(self, structure: AdminNavStructure) -> None:
        document = {
            "_id": _DEFAULT_DOC_ID,
            "nodes": admin_nav_structure_to_raw(structure),
            "updated_at": _as_utc(datetime.now(UTC)),
        }
        self._collection.replace_one(
            {"_id": _DEFAULT_DOC_ID},
            document,
            upsert=True,
        )
