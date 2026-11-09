from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import ShopListLastSucceededSnapshotStore
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListIntendedLine,
    ShopListLastSucceededSnapshot,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

# Sibling of journal collection; no new env (design: no new settings).
_BASELINE_COLLECTION = "shop_list_last_succeeded_snapshot"


@runtime_checkable
class ShopListLastSucceededSnapshotCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
def _line_to_document(line: ShopListIntendedLine) -> dict[str, Any]:
    return {
        "product_code": line.product_code,
        "price_rub": str(line.price_rub),
        "kit_group_id": line.kit_group_id,
        "availability_off": line.availability_off,
    }


@beartype
def _line_from_document(document: dict[str, Any]) -> ShopListIntendedLine:
    product_code = document.get("product_code")
    price_raw = document.get("price_rub")
    kit_group_id = document.get("kit_group_id")
    availability_off = document.get("availability_off", False)
    if not isinstance(product_code, str):
        raise ValueError("product_code must be str")
    if not isinstance(price_raw, str):
        raise ValueError("price_rub must be str")
    if not isinstance(kit_group_id, int):
        raise ValueError("kit_group_id must be int")
    if not isinstance(availability_off, bool):
        raise ValueError("availability_off must be bool")
    return ShopListIntendedLine(
        product_code=product_code,
        price_rub=Decimal(price_raw),
        kit_group_id=kit_group_id,
        availability_off=availability_off,
    )


@beartype
def _snapshot_to_document(snapshot: ShopListLastSucceededSnapshot) -> dict[str, Any]:
    return {
        "_id": snapshot.machine_code,
        "machine_code": snapshot.machine_code,
        "lines": [_line_to_document(line) for line in snapshot.lines],
        "updated_at": snapshot.updated_at,
    }


@beartype
def _snapshot_from_document(document: dict[str, Any]) -> ShopListLastSucceededSnapshot:
    machine_code = document.get("machine_code")
    updated_at = document.get("updated_at")
    lines_raw = document.get("lines", [])
    if not isinstance(machine_code, str):
        raise ValueError("machine_code must be str")
    if not isinstance(updated_at, datetime):
        raise ValueError("updated_at must be datetime")
    if not isinstance(lines_raw, list):
        raise ValueError("lines must be list")
    lines = tuple(_line_from_document(item) for item in lines_raw if isinstance(item, dict))
    return ShopListLastSucceededSnapshot(
        machine_code=machine_code,
        lines=lines,
        updated_at=updated_at,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoShopListLastSucceededSnapshotStore(ShopListLastSucceededSnapshotStore):
    collection: ShopListLastSucceededSnapshotCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoShopListLastSucceededSnapshotStore:
        collection = resolve_collection(
            mongo,
            collection_name=_BASELINE_COLLECTION,
            owner="MongoShopListLastSucceededSnapshotStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, machine_code: str) -> ShopListLastSucceededSnapshot | None:
        document = self.collection.find_one({"_id": machine_code})
        if document is None:
            return None
        return _snapshot_from_document(document)

    @beartype
    def upsert(self, snapshot: ShopListLastSucceededSnapshot) -> None:
        self.collection.replace_one(
            {"_id": snapshot.machine_code},
            _snapshot_to_document(snapshot),
            upsert=True,
        )
