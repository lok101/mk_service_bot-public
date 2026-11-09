from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale, SaleKind
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class SalesIngestCursorCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> object: ...


@runtime_checkable
class MachineSalesCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> object: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
        projection: dict[str, int] | None = None,
    ) -> Any: ...

    def find_one(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
        projection: dict[str, int] | None = None,
    ) -> dict[str, Any] | None: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _decimal_to_str(value: Decimal) -> str:
    return format(value, "f")


@beartype
def _decimal_from_document(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("decimal field must be str or Decimal")


@beartype
def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal_from_document(value)


@beartype
def machine_sale_to_document(sale: MachineSale) -> dict[str, Any]:
    document: dict[str, Any] = {
        "source_id": sale.source_id,
        "machine_id": sale.machine_id.value,
        "product_code": sale.product_code,
        "quantity": _decimal_to_str(sale.quantity),
        "occurred_at": _as_utc(sale.occurred_at),
        "ingested_at": _as_utc(sale.ingested_at),
        "sale_kind": sale.sale_kind,
    }
    if sale.kit_matrix_id is not None:
        document["kit_matrix_id"] = sale.kit_matrix_id
    if sale.kit_vending_machine_id is not None:
        document["kit_vending_machine_id"] = sale.kit_vending_machine_id
    if sale.kit_line_number is not None:
        document["kit_line_number"] = sale.kit_line_number
    if sale.machine_code is not None:
        document["machine_code"] = sale.machine_code
    if sale.resolve_status is not None:
        document["resolve_status"] = sale.resolve_status
    if sale.price is not None:
        document["price"] = _decimal_to_str(sale.price)
    if sale.company_id is not None:
        document["company_id"] = sale.company_id
    if sale.kit_vending_company_id is not None:
        document["kit_vending_company_id"] = sale.kit_vending_company_id
    if sale.domain_product_id != "":
        document["domain_product_id"] = sale.domain_product_id
    return document


@beartype
def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError("expected int or None")


@beartype
def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError("expected str or None")


@beartype
def machine_sale_from_document(document: dict[str, Any]) -> MachineSale:
    source_id = document.get("source_id")
    machine_id = document.get("machine_id")
    product_code = document.get("product_code")
    quantity = document.get("quantity")
    occurred_at = document.get("occurred_at")
    ingested_at = document.get("ingested_at")
    sale_kind_raw = document.get("sale_kind", "unknown")
    if (
        not isinstance(source_id, str)
        or not isinstance(machine_id, str)
        or not isinstance(product_code, str)
        or not isinstance(occurred_at, datetime)
        or not isinstance(ingested_at, datetime)
    ):
        raise ValueError("Machine sale document has invalid shape")
    if sale_kind_raw not in {"coffee", "snack", "unknown", "micromarket"}:
        raise ValueError("sale_kind must be coffee, snack, unknown, or micromarket")
    sale_kind: SaleKind = sale_kind_raw
    domain_product_id = document.get("domain_product_id", "")
    if not isinstance(domain_product_id, str):
        raise ValueError("domain_product_id must be str")
    return MachineSale(
        source_id=source_id,
        machine_id=MachineId(machine_id),
        product_code=product_code,
        quantity=_decimal_from_document(quantity),
        occurred_at=_as_utc(occurred_at),
        ingested_at=_as_utc(ingested_at),
        sale_kind=sale_kind,
        kit_matrix_id=_optional_int(document.get("kit_matrix_id")),
        kit_vending_machine_id=_optional_int(document.get("kit_vending_machine_id")),
        kit_line_number=_optional_int(document.get("kit_line_number")),
        machine_code=_optional_str(document.get("machine_code")),
        resolve_status=_optional_str(document.get("resolve_status")),
        price=_optional_decimal(document.get("price")),
        company_id=_optional_int(document.get("company_id")),
        kit_vending_company_id=_optional_int(document.get("kit_vending_company_id")),
        domain_product_id=domain_product_id,
    )


_KITVENDING_GLOBAL_CURSOR_ID = "kitvending_global"
_SALES_INGEST_CURSORS_COLLECTION = "sales_ingest_cursors"
_MISSING_PRICE_FILTER: dict[str, Any] = {
    "$or": [{"price": {"$exists": False}}, {"price": None}],
}
_MISSING_COMPANY_ID_FILTER: dict[str, Any] = {
    "$or": [{"company_id": {"$exists": False}}, {"company_id": None}],
}


@beartype
@dataclass(frozen=True, slots=True)
class MongoMachineSalesStore(MachineSalesStore):
    _collection: MachineSalesCollection
    _cursor_collection: SalesIngestCursorCollection | None = None

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: MachineSalesCollection,
        *,
        cursor_collection: SalesIngestCursorCollection | None = None,
    ) -> MongoMachineSalesStore:
        store = cls(_collection=collection, _cursor_collection=cursor_collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMachineSalesStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.machine_sales_collection,
            owner="MongoMachineSalesStore",
            client=client,
        )
        cursor_collection = resolve_collection(
            settings,
            collection_name=_SALES_INGEST_CURSORS_COLLECTION,
            owner="MongoMachineSalesStore",
            client=client,
        )
        return cls.from_collection(collection, cursor_collection=cursor_collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            "source_id",
            unique=True,
            name="machine_sales_source_id_unique",
        )
        self._collection.create_index(
            [("machine_id", ASCENDING), ("occurred_at", ASCENDING)],
            name="machine_sales_machine_occurred_at",
        )

    @beartype
    def insert_if_absent(self, sale: MachineSale) -> bool:
        document = machine_sale_to_document(sale)
        try:
            self._collection.insert_one(document)
            return True
        except DuplicateKeyError:
            return False

    @beartype
    def set_resolve_status(self, source_id: str, resolve_status: str) -> None:
        result = self._collection.update_one(
            {"source_id": source_id},
            {"$set": {"resolve_status": resolve_status}},
        )
        matched = getattr(result, "matched_count", None)
        if matched == 0:
            raise KeyError(f"machine sale not found: {source_id}")

    @beartype
    def find_in_window(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        opened_at_utc = _as_utc(opened_at)
        closed_at_utc = _as_utc(closed_at)
        cursor = self._collection.find(
            {
                "machine_id": machine_id.value,
                "occurred_at": {"$gt": opened_at_utc, "$lte": closed_at_utc},
            },
            sort=[("occurred_at", ASCENDING)],
        )
        return tuple(machine_sale_from_document(document) for document in cursor)

    @beartype
    def find_in_global_window(
        self,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        opened_at_utc = _as_utc(opened_at)
        closed_at_utc = _as_utc(closed_at)
        cursor = self._collection.find(
            {
                "occurred_at": {"$gte": opened_at_utc, "$lt": closed_at_utc},
            },
            sort=[("occurred_at", ASCENDING)],
        )
        return tuple(machine_sale_from_document(document) for document in cursor)

    @beartype
    def list_source_ids(
        self,
        *,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
    ) -> frozenset[str]:
        return frozenset(
            sale.source_id
            for sale in self.find_in_window(
                machine_id,
                opened_at=opened_at,
                closed_at=closed_at,
            )
        )

    @beartype
    def find_after_by_machine_code(
        self,
        machine_code: str,
        *,
        after: datetime,
    ) -> tuple[MachineSale, ...]:
        after_utc = _as_utc(after)
        cursor = self._collection.find(
            {
                "machine_code": machine_code,
                "occurred_at": {"$gt": after_utc},
            },
            sort=[("occurred_at", ASCENDING)],
        )
        return tuple(machine_sale_from_document(document) for document in cursor)

    @beartype
    def last_occurred_at(self, machine_id: MachineId) -> datetime | None:
        document = self._collection.find_one(
            {"machine_id": machine_id.value},
            sort=[("occurred_at", -1)],
            projection={"occurred_at": 1},
        )
        if document is None:
            return None
        occurred_at = document.get("occurred_at")
        if not isinstance(occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        return _as_utc(occurred_at)

    @beartype
    def max_occurred_at(self) -> datetime | None:
        document = self._collection.find_one(
            {},
            sort=[("occurred_at", -1)],
            projection={"occurred_at": 1},
        )
        if document is None:
            return None
        occurred_at = document.get("occurred_at")
        if not isinstance(occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        return _as_utc(occurred_at)

    @beartype
    def load_global_cursor(self) -> datetime | None:
        persisted = self._load_persisted_watermark()
        sales_max = self.max_occurred_at()
        if persisted is None:
            return sales_max
        if sales_max is None:
            return persisted
        return max(persisted, sales_max)

    @beartype
    def save_global_cursor(self, watermark: datetime) -> None:
        if self._cursor_collection is None:
            return
        self._cursor_collection.replace_one(
            {"_id": _KITVENDING_GLOBAL_CURSOR_ID},
            {"_id": _KITVENDING_GLOBAL_CURSOR_ID, "occurred_at": _as_utc(watermark)},
            upsert=True,
        )

    @beartype
    def _load_persisted_watermark(self) -> datetime | None:
        if self._cursor_collection is None:
            return None
        document = self._cursor_collection.find_one({"_id": _KITVENDING_GLOBAL_CURSOR_ID})
        if document is None:
            return None
        occurred_at = document.get("occurred_at")
        if not isinstance(occurred_at, datetime):
            raise ValueError("cursor occurred_at must be a datetime")
        return _as_utc(occurred_at)

    @beartype
    def set_price_if_absent(self, source_id: str, price: Decimal) -> bool:
        result = self._collection.update_one(
            {"source_id": source_id, **_MISSING_PRICE_FILTER},
            {"$set": {"price": _decimal_to_str(price)}},
        )
        matched = getattr(result, "matched_count", None)
        return bool(matched)

    @beartype
    def patch_company_id_if_missing(self, source_id: str, company_id: int) -> bool:
        result = self._collection.update_one(
            {"source_id": source_id, **_MISSING_COMPANY_ID_FILTER},
            {"$set": {"company_id": company_id}},
        )
        matched = getattr(result, "matched_count", None)
        return bool(matched)

    @beartype
    def list_with_missing_company_id(self) -> tuple[MachineSale, ...]:
        cursor = self._collection.find(
            _MISSING_COMPANY_ID_FILTER,
            sort=[("occurred_at", ASCENDING), ("source_id", ASCENDING)],
        )
        return tuple(machine_sale_from_document(document) for document in cursor)

    @beartype
    def list_machine_ids_with_sales(self) -> tuple[MachineId, ...]:
        cursor = self._collection.find({}, projection={"machine_id": 1})
        seen: set[str] = set()
        for document in cursor:
            machine_id = document.get("machine_id")
            if isinstance(machine_id, str):
                seen.add(machine_id)
        return tuple(MachineId(value) for value in sorted(seen))

    @beartype
    def list_with_company_id(self, machine_id: MachineId) -> tuple[MachineSale, ...]:
        cursor = self._collection.find(
            {
                "machine_id": machine_id.value,
                "company_id": {"$ne": None, "$exists": True},
            },
            sort=[("occurred_at", ASCENDING), ("source_id", ASCENDING)],
        )
        return tuple(machine_sale_from_document(document) for document in cursor)

    @beartype
    def min_occurred_at_missing_price(self) -> datetime | None:
        document = self._collection.find_one(
            _MISSING_PRICE_FILTER,
            sort=[("occurred_at", ASCENDING)],
            projection={"occurred_at": 1},
        )
        if document is None:
            return None
        occurred_at = document.get("occurred_at")
        if not isinstance(occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        return _as_utc(occurred_at)

    @beartype
    def find_missing_price_before(self, before: datetime) -> tuple[MachineSale, ...]:
        before_utc = _as_utc(before)
        cursor = self._collection.find(
            {**_MISSING_PRICE_FILTER, "occurred_at": {"$lt": before_utc}},
            sort=[("occurred_at", ASCENDING)],
        )
        return tuple(machine_sale_from_document(document) for document in cursor)
