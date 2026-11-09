from __future__ import annotations

import time
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient, ReturnDocument

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

COLLECTION_NAME = "kitvending_request_ids"


_MongoDatabaseSource = MongoDatabaseSource


@runtime_checkable
class KitVendingRequestIdsCollection(Protocol):
    def find_one_and_update(
        self,
        filter: dict[str, Any],
        update: list[dict[str, Any]] | dict[str, Any],
        *,
        upsert: bool = False,
        return_document: bool = ...,
    ) -> dict[str, Any] | None: ...


@beartype
class MongoKitVendingRequestIdStore:
    def __init__(self, collection: KitVendingRequestIdsCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: KitVendingRequestIdsCollection,
    ) -> MongoKitVendingRequestIdStore:
        return cls(collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoKitVendingRequestIdStore:
        collection = resolve_collection(
            settings,
            collection_name=COLLECTION_NAME,
            owner="MongoKitVendingRequestIdStore",
            client=cast(MongoClient[dict[str, Any]] | None, client),
        )
        return cls.from_collection(collection)

    @beartype
    def next_id(self, *, login: str) -> int:
        floor_ms = int(time.time() * 1000)
        document = self._collection.find_one_and_update(
            {"_id": login},
            [
                {
                    "$set": {
                        "last_request_id": {
                            "$max": [
                                {"$add": [{"$ifNull": ["$last_request_id", 0]}, 1]},
                                floor_ms,
                            ]
                        }
                    }
                }
            ],
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise RuntimeError("Mongo find_one_and_update returned no document")
        return int(document["last_request_id"])

    @beartype
    def bump_floor(self, *, login: str, floor: int) -> None:
        self._collection.find_one_and_update(
            {"_id": login},
            [
                {
                    "$set": {
                        "last_request_id": {
                            "$max": [
                                {"$ifNull": ["$last_request_id", 0]},
                                floor,
                            ]
                        }
                    }
                }
            ],
            upsert=True,
        )


__all__ = ["MongoDatabaseSource", "MongoKitVendingRequestIdStore"]
