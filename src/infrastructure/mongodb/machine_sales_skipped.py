from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.inventory_reconciliation.sale_skip import (
    MachineSaleSkip,
    SaleSkipReasonClass,
)
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection

_VALID_REASON_CLASSES: frozenset[str] = frozenset(
    {
        "critical_product_resolve",
        "no_machine_code",
        "line_neg_1",
        "product_zero",
    },
)


@runtime_checkable
class MachineSaleSkipCollection(Protocol):
    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
def machine_sale_skip_to_set_fields(skip: MachineSaleSkip) -> dict[str, Any]:
    return {
        "source_id": skip.source_id,
        "reason_class": skip.reason_class,
        "kit_vending_machine_id": skip.kit_vending_machine_id,
        "vending_machine_name": skip.vending_machine_name,
        "occurred_at": _as_utc(skip.occurred_at),
        "line_number": skip.line_number,
        "matrix_id": skip.matrix_id,
        "goods_name": skip.goods_name,
        "external_id": skip.external_id,
        "last_seen_at": _as_utc(skip.last_seen_at),
    }


@beartype
def machine_sale_skip_from_document(document: dict[str, Any]) -> MachineSaleSkip:
    source_id = document.get("source_id")
    reason_class = document.get("reason_class")
    kit_vending_machine_id = document.get("kit_vending_machine_id")
    occurred_at = document.get("occurred_at")
    line_number = document.get("line_number")
    first_seen_at = document.get("first_seen_at")
    last_seen_at = document.get("last_seen_at")
    if (
        not isinstance(source_id, str)
        or not isinstance(reason_class, str)
        or not isinstance(kit_vending_machine_id, int)
        or isinstance(kit_vending_machine_id, bool)
        or not isinstance(occurred_at, datetime)
        or not isinstance(line_number, int)
        or isinstance(line_number, bool)
        or not isinstance(first_seen_at, datetime)
        or not isinstance(last_seen_at, datetime)
    ):
        raise ValueError("MachineSaleSkip document has invalid shape")
    if reason_class not in _VALID_REASON_CLASSES:
        raise ValueError(f"invalid reason_class: {reason_class}")
    typed_reason: SaleSkipReasonClass = reason_class  # type: ignore[assignment]
    return MachineSaleSkip(
        source_id=source_id,
        reason_class=typed_reason,
        kit_vending_machine_id=kit_vending_machine_id,
        vending_machine_name=_optional_str(document.get("vending_machine_name")),
        occurred_at=_as_utc(occurred_at),
        line_number=line_number,
        matrix_id=_optional_int(document.get("matrix_id")),
        goods_name=_optional_str(document.get("goods_name")),
        external_id=_optional_str(document.get("external_id")),
        first_seen_at=_as_utc(first_seen_at),
        last_seen_at=_as_utc(last_seen_at),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMachineSaleSkipStore(MachineSaleSkipStore):
    _collection: MachineSaleSkipCollection

    @classmethod
    @beartype
    def from_collection(cls, collection: MachineSaleSkipCollection) -> MongoMachineSaleSkipStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMachineSaleSkipStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.machine_sales_skipped_collection,
            owner="MongoMachineSaleSkipStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            "source_id",
            unique=True,
            name="machine_sales_skipped_source_id_unique",
        )

    @beartype
    def upsert(self, skip: MachineSaleSkip) -> None:
        self._collection.update_one(
            {"source_id": skip.source_id},
            {
                "$set": machine_sale_skip_to_set_fields(skip),
                "$setOnInsert": {"first_seen_at": _as_utc(skip.first_seen_at)},
            },
            upsert=True,
        )

    @beartype
    def get(self, source_id: str) -> MachineSaleSkip | None:
        document = self._collection.find_one({"source_id": source_id})
        if document is None:
            return None
        return machine_sale_skip_from_document(document)

    @beartype
    def delete_by_source_id(self, source_id: str) -> bool:
        result = self._collection.delete_one({"source_id": source_id})
        deleted = getattr(result, "deleted_count", 0)
        return deleted > 0
