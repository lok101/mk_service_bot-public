from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import MicromarketWarehouseStockSnapshotPort
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_LOGGER = logging.getLogger(__name__)
_SCHEMA_VERSION = 1
_DOC_ID = "main"


@runtime_checkable
class WarehouseStockSnapshotCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...


@beartype
def _qty_map_to_document(qty: Mapping[str, Decimal]) -> dict[str, str]:
    return {code: str(value) for code, value in qty.items()}


@beartype
def _qty_map_from_document(raw: object) -> dict[str, Decimal]:
    if not isinstance(raw, dict):
        raise ValueError("qty_by_catalog_code must be dict")
    result: dict[str, Decimal] = {}
    for code, value in raw.items():
        if not isinstance(code, str):
            raise ValueError("catalog code must be str")
        try:
            result[code] = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"invalid qty for {code}") from exc
    return result


@beartype
def _snapshot_to_document(snapshot: MainWarehouseStockSnapshot) -> dict[str, Any]:
    return {
        "_id": _DOC_ID,
        "warehouse_id": str(snapshot.warehouse_id),
        "refreshed_at": snapshot.refreshed_at,
        "qty_by_catalog_code": _qty_map_to_document(snapshot.qty_by_catalog_code),
        "schema_version": _SCHEMA_VERSION,
    }


@beartype
def _snapshot_from_document(document: dict[str, Any]) -> MainWarehouseStockSnapshot:
    warehouse_raw = document.get("warehouse_id")
    refreshed_at = document.get("refreshed_at")
    if not isinstance(warehouse_raw, str):
        raise ValueError("warehouse_id must be str")
    if not isinstance(refreshed_at, datetime):
        raise ValueError("refreshed_at must be datetime")
    return MainWarehouseStockSnapshot(
        warehouse_id=UUID(warehouse_raw),
        refreshed_at=refreshed_at,
        qty_by_catalog_code=_qty_map_from_document(document.get("qty_by_catalog_code")),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketWarehouseStockSnapshotStore(MicromarketWarehouseStockSnapshotPort):
    collection: WarehouseStockSnapshotCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketWarehouseStockSnapshotStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_warehouse_stock_snapshot_collection,
            owner="MongoMicromarketWarehouseStockSnapshotStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self) -> MainWarehouseStockSnapshot | None:
        document = self.collection.find_one({"_id": _DOC_ID})
        if document is None:
            return None
        return _snapshot_from_document(document)

    @beartype
    def replace(self, snapshot: MainWarehouseStockSnapshot) -> None:
        self.collection.replace_one(
            {"_id": _DOC_ID},
            _snapshot_to_document(snapshot),
            upsert=True,
        )

    @beartype
    def apply_delta(self, *, deltas: Mapping[str, Decimal]) -> None:
        current = self.get()
        if current is None:
            _LOGGER.warning("micromarket_warehouse_stock_delta_without_snapshot")
            return
        qty = dict(current.qty_by_catalog_code)
        for code, delta in deltas.items():
            if not code:
                continue
            if code not in qty:
                _LOGGER.warning(
                    "micromarket_warehouse_stock_delta_missing_code",
                    extra={"catalog_code": code},
                )
            next_qty = qty.get(code, Decimal("0")) + delta
            if next_qty < 0:
                _LOGGER.warning(
                    "micromarket_warehouse_stock_delta_clamped",
                    extra={"catalog_code": code, "raw": str(next_qty)},
                )
                next_qty = Decimal("0")
            qty[code] = next_qty
        self.replace(
            MainWarehouseStockSnapshot(
                warehouse_id=current.warehouse_id,
                refreshed_at=current.refreshed_at,
                qty_by_catalog_code=qty,
            ),
        )
