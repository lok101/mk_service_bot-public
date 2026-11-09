from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class KitShopSaleReceiptCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def insert_one(self, document: dict[str, Any]) -> object: ...

    def create_index(self, keys: list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
class MongoKitShopSaleReceiptStore:
    def __init__(self, collection: KitShopSaleReceiptCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoKitShopSaleReceiptStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.kitshop_sale_receipts_collection,
            owner="MongoKitShopSaleReceiptStore",
            client=client,
        )
        collection.create_index(
            [("sale_id", ASCENDING)],
            unique=True,
            name="kitshop_sale_receipts_sale_id_unique",
        )
        return cls(collection)

    @beartype
    def load(self, sale_id: int) -> dict[str, object] | None:
        document = self._collection.find_one({"_id": sale_id})
        if document is None:
            return None
        payload = document.get("payload")
        if not isinstance(payload, dict):
            return None
        return dict(payload)

    @beartype
    def save_if_absent(self, *, sale_id: int, payload: dict[str, object]) -> None:
        try:
            self._collection.insert_one(
                {"_id": sale_id, "sale_id": sale_id, "payload": dict(payload)},
            )
        except DuplicateKeyError:
            return
