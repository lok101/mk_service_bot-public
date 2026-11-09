from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import SupplyOrderCategoryFactsSnapshotPort
from src.application.micromarket_loading.supply_order_category_snapshot import (
    SupplyOrderCategoryFactRow,
    SupplyOrderCategoryFactsSnapshot,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_SCHEMA_VERSION = 1
_DOC_ID = "main"


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@runtime_checkable
class CategoryFactsSnapshotCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...


@beartype
def _facts_to_document(
    facts: dict[str, SupplyOrderCategoryFactRow],
) -> dict[str, dict[str, Any]]:
    return {
        code: {
            "folder_ancestor_ids": list(row.folder_ancestor_ids),
            "shelf_life_days": row.shelf_life_days,
        }
        for code, row in facts.items()
    }


@beartype
def _facts_from_document(raw: object) -> dict[str, SupplyOrderCategoryFactRow]:
    if not isinstance(raw, dict):
        raise ValueError("facts_by_catalog_code must be dict")
    result: dict[str, SupplyOrderCategoryFactRow] = {}
    for code, value in raw.items():
        if not isinstance(code, str) or not isinstance(value, dict):
            raise ValueError("invalid fact row")
        ancestors_raw = value.get("folder_ancestor_ids")
        if not isinstance(ancestors_raw, list) or not all(
            isinstance(item, str) for item in ancestors_raw
        ):
            raise ValueError("folder_ancestor_ids must be list[str]")
        days = value.get("shelf_life_days")
        if days is not None and not isinstance(days, int):
            raise ValueError("shelf_life_days must be int|null")
        result[code] = SupplyOrderCategoryFactRow(
            folder_ancestor_ids=tuple(ancestors_raw),
            shelf_life_days=days,
        )
    return result


@beartype
def _snapshot_to_document(snapshot: SupplyOrderCategoryFactsSnapshot) -> dict[str, Any]:
    return {
        "_id": _DOC_ID,
        "refreshed_at": _as_utc(snapshot.refreshed_at),
        "facts_by_catalog_code": _facts_to_document(dict(snapshot.facts_by_catalog_code)),
        "schema_version": _SCHEMA_VERSION,
    }


@beartype
def _snapshot_from_document(document: dict[str, Any]) -> SupplyOrderCategoryFactsSnapshot:
    refreshed_at = document.get("refreshed_at")
    if not isinstance(refreshed_at, datetime):
        raise ValueError("refreshed_at must be datetime")
    return SupplyOrderCategoryFactsSnapshot(
        refreshed_at=_as_utc(refreshed_at),
        facts_by_catalog_code=_facts_from_document(document.get("facts_by_catalog_code")),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoSupplyOrderCategoryFactsSnapshotStore(SupplyOrderCategoryFactsSnapshotPort):
    collection: CategoryFactsSnapshotCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoSupplyOrderCategoryFactsSnapshotStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_supply_order_category_snapshot_collection,
            owner="MongoSupplyOrderCategoryFactsSnapshotStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self) -> SupplyOrderCategoryFactsSnapshot | None:
        document = self.collection.find_one({"_id": _DOC_ID})
        if document is None:
            return None
        return _snapshot_from_document(document)

    @beartype
    def replace(self, snapshot: SupplyOrderCategoryFactsSnapshot) -> None:
        self.collection.replace_one(
            {"_id": _DOC_ID},
            _snapshot_to_document(snapshot),
            upsert=True,
        )
