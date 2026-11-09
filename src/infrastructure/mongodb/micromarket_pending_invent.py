from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import PendingMicromarketInventStore
from src.config.mongodb import MongoSettings
from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class PendingMicromarketInventCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _pending_to_doc(pending: PendingMicromarketInvent) -> dict[str, Any]:
    return {
        "_id": pending.machine_code,
        "inventory_id": pending.inventory_id,
        "quantities": [{"product_code": code, "qty": str(qty)} for code, qty in pending.quantities],
        "submitted_at": pending.submitted_at,
        "operational_day": pending.operational_day.isoformat(),
        "performed_technician_id": pending.performed_technician_id,
        "performed_technician_name": pending.performed_technician_name,
        "assigned_technician_id": pending.assigned_technician_id,
        "assigned_technician_name": pending.assigned_technician_name,
        "machine_name": pending.machine_name,
    }


@beartype
def _pending_from_doc(document: Mapping[str, Any]) -> PendingMicromarketInvent:
    submitted_raw = document["submitted_at"]
    if not isinstance(submitted_raw, datetime):
        raise TypeError("submitted_at must be datetime")
    quantities = tuple(
        (str(item["product_code"]), Decimal(str(item["qty"])))
        for item in document.get("quantities", [])
    )
    return PendingMicromarketInvent(
        machine_code=str(document["_id"]),
        inventory_id=str(document["inventory_id"]),
        quantities=quantities,
        submitted_at=submitted_raw,
        operational_day=date.fromisoformat(str(document["operational_day"])),
        performed_technician_id=str(document.get("performed_technician_id", "")),
        performed_technician_name=str(document.get("performed_technician_name", "")),
        assigned_technician_id=str(document.get("assigned_technician_id", "")),
        assigned_technician_name=str(document.get("assigned_technician_name", "")),
        machine_name=str(document.get("machine_name", "")),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoPendingMicromarketInventStore(PendingMicromarketInventStore):
    collection: PendingMicromarketInventCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoPendingMicromarketInventStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_pending_invent_collection,
            owner="MongoPendingMicromarketInventStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get_for_machine(self, machine_code: str) -> PendingMicromarketInvent | None:
        document = self.collection.find_one({"_id": machine_code})
        if document is None:
            return None
        return _pending_from_doc(document)

    @beartype
    def save(self, pending: PendingMicromarketInvent) -> None:
        self.collection.replace_one(
            {"_id": pending.machine_code},
            _pending_to_doc(pending),
            upsert=True,
        )

    @beartype
    def clear(self, machine_code: str) -> None:
        self.collection.delete_one({"_id": machine_code})
