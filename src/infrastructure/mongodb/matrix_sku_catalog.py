from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.ports import MatrixSkuCatalogStore
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MatrixSkuCatalogCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _entry_to_document(entry: MatrixSkuCatalogEntry) -> dict[str, Any]:
    return {
        "_id": entry.product_code,
        "display_name": entry.display_name,
        "capacity": entry.capacity,
        "product_multiplier": str(entry.product_multiplier),
    }


@beartype
def _entry_from_document(document: dict[str, Any]) -> MatrixSkuCatalogEntry:
    id_raw = document.get("_id", document.get("product_code"))
    display_name = document.get("display_name")
    capacity = document.get("capacity")
    multiplier_raw = document.get("product_multiplier")
    if not isinstance(id_raw, str):
        raise ValueError("product_code must be str")
    if not isinstance(display_name, str):
        raise ValueError("display_name must be str")
    if not isinstance(capacity, int):
        raise ValueError("capacity must be int")
    try:
        product_multiplier = Decimal(str(multiplier_raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("product_multiplier must be Decimal-compatible") from exc
    return MatrixSkuCatalogEntry(
        product_code=id_raw,
        display_name=display_name,
        capacity=capacity,
        product_multiplier=product_multiplier,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMatrixSkuCatalogStore(MatrixSkuCatalogStore):
    collection: MatrixSkuCatalogCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMatrixSkuCatalogStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.matrix_sku_catalog_collection,
            owner="MongoMatrixSkuCatalogStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, product_code: str) -> MatrixSkuCatalogEntry | None:
        document = self.collection.find_one({"_id": product_code})
        if document is None:
            return None
        return _entry_from_document(document)

    @beartype
    def upsert(self, entry: MatrixSkuCatalogEntry) -> None:
        self.collection.replace_one(
            {"_id": entry.product_code},
            _entry_to_document(entry),
            upsert=True,
        )

    @beartype
    def list_all(self) -> tuple[MatrixSkuCatalogEntry, ...]:
        items: list[MatrixSkuCatalogEntry] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_entry_from_document(document))
        items.sort(key=lambda entry: entry.product_code)
        return tuple(items)
