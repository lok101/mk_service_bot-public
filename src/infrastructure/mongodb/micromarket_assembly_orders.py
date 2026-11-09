from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import MicromarketAssemblyOrderStore
from src.config.mongodb import MongoSettings
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
)
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MicromarketAssemblyOrderCollection(Protocol):
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
def _line_to_doc(line: MicromarketAssemblyOrderLine) -> dict[str, str]:
    return {"catalog_code": line.catalog_code, "qty": str(line.qty)}


@beartype
def _line_from_doc(document: Mapping[str, Any]) -> MicromarketAssemblyOrderLine:
    return MicromarketAssemblyOrderLine(
        catalog_code=str(document["catalog_code"]),
        qty=Decimal(str(document["qty"])),
    )


@beartype
def _order_to_doc(order: MicromarketAssemblyOrder) -> dict[str, Any]:
    return {
        "_id": order.order_id,
        "machine_code": order.machine_code,
        "status": order.status.value,
        "created_at": order.created_at,
        "lines": [_line_to_doc(line) for line in order.lines],
        "alerted_days": [day.isoformat() for day in sorted(order.alerted_days)],
    }


@beartype
def _order_from_doc(document: Mapping[str, Any]) -> MicromarketAssemblyOrder:
    created_raw = document.get("created_at")
    created_at = created_raw if isinstance(created_raw, datetime) else None
    alerted = {date.fromisoformat(str(day)) for day in document.get("alerted_days", [])}
    lines = tuple(_line_from_doc(item) for item in document.get("lines", []))
    return MicromarketAssemblyOrder(
        order_id=str(document["_id"]),
        machine_code=str(document["machine_code"]),
        lines=lines,
        status=AssemblyOrderStatus(str(document["status"])),
        created_at=created_at,
        alerted_days=alerted,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketAssemblyOrderStore(MicromarketAssemblyOrderStore):
    collection: MicromarketAssemblyOrderCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketAssemblyOrderStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_assembly_orders_collection,
            owner="MongoMicromarketAssemblyOrderStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, order_id: str) -> MicromarketAssemblyOrder | None:
        document = self.collection.find_one({"_id": order_id})
        if document is None:
            return None
        return _order_from_doc(document)

    @beartype
    def list_open(self) -> tuple[MicromarketAssemblyOrder, ...]:
        cursor = self.collection.find({"status": AssemblyOrderStatus.OPEN.value})
        return tuple(_order_from_doc(doc) for doc in cursor)

    @beartype
    def list_open_for_machine(self, machine_code: str) -> tuple[MicromarketAssemblyOrder, ...]:
        cursor = self.collection.find(
            {
                "status": AssemblyOrderStatus.OPEN.value,
                "machine_code": machine_code,
            }
        )
        return tuple(_order_from_doc(doc) for doc in cursor)

    @beartype
    def save(self, order: MicromarketAssemblyOrder) -> None:
        self.collection.replace_one(
            {"_id": order.order_id},
            _order_to_doc(order),
            upsert=True,
        )
