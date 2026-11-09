from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.config.mongodb import MongoSettings
from src.config.product_procurement_mirror import ProductProcurementMirrorSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class ProcurementMirrorCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Iterable[dict[str, Any]]: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...


@beartype
class MongoProcurementMirrorStore:
    def __init__(self, collection: ProcurementMirrorCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_collection(
        cls, collection: ProcurementMirrorCollection
    ) -> MongoProcurementMirrorStore:
        return cls(collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongodb: MongoSettings,
        mirror: ProductProcurementMirrorSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoProcurementMirrorStore:
        collection = resolve_collection(
            mongodb,
            collection_name=mirror.collection,
            owner="MongoProcurementMirrorStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def get(self, catalog_code: str) -> ProcurementMirror | None:
        document = self._collection.find_one({"_id": catalog_code})
        if document is None:
            return None
        return _from_document(document)

    @beartype
    def upsert(self, mirror: ProcurementMirror) -> None:
        self._collection.replace_one(
            {"_id": mirror.catalog_code},
            _to_document(mirror),
            upsert=True,
        )

    @beartype
    def delete(self, catalog_code: str) -> None:
        self._collection.delete_one({"_id": catalog_code})

    @beartype
    def codes(self) -> tuple[str, ...]:
        return tuple(str(document["_id"]) for document in self._collection.find({}))


@beartype
def _to_document(mirror: ProcurementMirror) -> dict[str, Any]:
    price: str | None = None
    if mirror.last_buy_price is not None:
        price = format(mirror.last_buy_price, "f")
    package_qty: str | None = None
    if mirror.package_quantity is not None:
        package_qty = format(mirror.package_quantity, "f")
    return {
        "_id": mirror.catalog_code,
        "catalog_code": mirror.catalog_code,
        "supplier_id": mirror.supplier_id,
        "supplier_name": mirror.supplier_name,
        "last_buy_price": price,
        "supply_moment": mirror.supply_moment,
        "synced_at": mirror.synced_at,
        "package_quantity": package_qty,
        "supplier_product_name": mirror.supplier_product_name,
    }


@beartype
def _from_document(document: dict[str, Any]) -> ProcurementMirror:
    raw_price = document.get("last_buy_price")
    last_buy_price: Decimal | None = None
    if isinstance(raw_price, str) and raw_price.strip():
        last_buy_price = Decimal(raw_price)
    elif isinstance(raw_price, Decimal):
        last_buy_price = raw_price
    raw_pkg = document.get("package_quantity")
    package_quantity: Decimal | None = None
    if isinstance(raw_pkg, str) and raw_pkg.strip():
        package_quantity = Decimal(raw_pkg)
    elif isinstance(raw_pkg, Decimal):
        package_quantity = raw_pkg
    return ProcurementMirror(
        catalog_code=str(document["_id"]),
        supplier_id=_optional_str(document.get("supplier_id")),
        supplier_name=_optional_str(document.get("supplier_name")),
        last_buy_price=last_buy_price,
        supply_moment=_as_utc_datetime(document.get("supply_moment")),
        synced_at=_require_utc_datetime(document.get("synced_at")),
        package_quantity=package_quantity,
        supplier_product_name=_optional_str(document.get("supplier_product_name")),
    )


def _as_utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_utc_datetime(value: object) -> datetime:
    moment = _as_utc_datetime(value)
    if moment is None:
        msg = "synced_at must be datetime"
        raise TypeError(msg)
    return moment


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None
