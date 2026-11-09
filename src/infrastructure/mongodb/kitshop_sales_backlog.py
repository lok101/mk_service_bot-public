from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class KitShopSalesBacklogCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
        limit: int = 0,
    ) -> Any: ...

    def insert_one(self, document: dict[str, Any]) -> object: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> object: ...


@beartype
class MongoKitShopSalesBacklogStore:
    def __init__(self, collection: KitShopSalesBacklogCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: KitShopSalesBacklogCollection,
    ) -> MongoKitShopSalesBacklogStore:
        return cls(collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoKitShopSalesBacklogStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.kitshop_sales_backlog_collection,
            owner="MongoKitShopSalesBacklogStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def upsert_pending(self, *, sale_id: int) -> bool:
        try:
            self._collection.insert_one(
                {
                    "_id": sale_id,
                    "sale_id": sale_id,
                    "status": "pending",
                },
            )
        except DuplicateKeyError:
            return False
        return True

    @beartype
    def claim_pending(self, *, limit: int = 1) -> list[int]:
        pending_cursor = self._collection.find(
            {"status": "pending"},
            sort=[("_id", ASCENDING)],
            limit=limit,
        )
        claimed = [int(document["_id"]) for document in pending_cursor]
        remaining = limit - len(claimed)
        if remaining <= 0:
            return claimed
        hold_cursor = self._collection.find(
            {"status": "hold"},
            sort=[("_id", ASCENDING)],
            limit=remaining,
        )
        claimed.extend(int(document["_id"]) for document in hold_cursor)
        return claimed

    @beartype
    def mark_done(self, *, sale_id: int) -> None:
        self._collection.update_one(
            {"_id": sale_id},
            {"$set": {"status": "done"}, "$unset": {"hold_reason": ""}},
        )

    @beartype
    def mark_hold(self, *, sale_id: int, reason: str) -> None:
        self._collection.update_one(
            {"_id": sale_id},
            {"$set": {"status": "hold", "hold_reason": reason}},
        )

    @beartype
    def get_status(self, sale_id: int) -> str | None:
        document = self._collection.find_one({"_id": sale_id})
        if document is None:
            return None
        status = document.get("status")
        return None if status is None else str(status)


__all__ = ["MongoKitShopSalesBacklogStore"]
