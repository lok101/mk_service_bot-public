from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import DESCENDING, MongoClient

from src.application.micromarket_loading.ports import MicromarketSupplyOrderStore
from src.config.mongodb import MongoSettings
from src.domain.micromarket_loading.supply_order import (
    MicromarketSupplyOrder,
    MicromarketSupplyOrderLine,
    MicromarketSupplyOrderMachine,
    SupplyOrderLineCategory,
)
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MicromarketSupplyOrderCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _order_to_document(order: MicromarketSupplyOrder) -> dict[str, Any]:
    return {
        "_id": order.order_id,
        "created_at": order.created_at,
        "expected_arrival_at": order.expected_arrival_at,
        "machines": [
            {
                "machine_id": machine.machine_id,
                "lines": [
                    {
                        "product_code": line.product_code,
                        "need_qty": str(line.need_qty),
                        "category": line.category,
                        "name": line.name,
                        "supplier_name": line.supplier_name,
                        "last_buy_price": (
                            format(line.last_buy_price, "f")
                            if line.last_buy_price is not None
                            else None
                        ),
                        "package_quantity": (
                            format(line.package_quantity, "f")
                            if line.package_quantity is not None
                            else None
                        ),
                        "supplier_product_name": line.supplier_product_name,
                        "gap_qty": str(line.gap_qty),
                        "forecast_qty": str(line.forecast_qty),
                    }
                    for line in machine.lines
                ],
            }
            for machine in order.machines
        ],
    }


@beartype
def _order_from_document(document: dict[str, Any]) -> MicromarketSupplyOrder:
    order_id = document.get("_id")
    created_at = document.get("created_at")
    expected_arrival_raw = document.get("expected_arrival_at")
    machines_raw = document.get("machines")
    if not isinstance(order_id, str):
        raise ValueError("order_id must be str")
    if not isinstance(created_at, datetime):
        raise ValueError("created_at must be datetime")
    # Legacy pre-arrival snapshots: fall back to created_at for list/download.
    if expected_arrival_raw is None:
        expected_arrival_at = created_at
    elif isinstance(expected_arrival_raw, datetime):
        expected_arrival_at = expected_arrival_raw
    else:
        raise ValueError("expected_arrival_at must be datetime")
    if not isinstance(machines_raw, list):
        raise ValueError("machines must be a list")
    machines: list[MicromarketSupplyOrderMachine] = []
    for machine_raw in machines_raw:
        if not isinstance(machine_raw, dict):
            raise ValueError("machine must be a dict")
        machine_id = machine_raw.get("machine_id")
        lines_raw = machine_raw.get("lines")
        if not isinstance(machine_id, str):
            raise ValueError("machine_id must be str")
        if not isinstance(lines_raw, list):
            raise ValueError("lines must be a list")
        lines: list[MicromarketSupplyOrderLine] = []
        for line_raw in lines_raw:
            if not isinstance(line_raw, dict):
                raise ValueError("line must be a dict")
            product_code = line_raw.get("product_code")
            need_raw = line_raw.get("need_qty")
            category_raw = line_raw.get("category")
            name = line_raw.get("name", "")
            if not isinstance(product_code, str):
                raise ValueError("product_code must be str")
            if not isinstance(need_raw, str):
                raise ValueError("need_qty must be str")
            category = _parse_line_category(category_raw)
            if not isinstance(name, str):
                raise ValueError("name must be str")
            forecast_raw = line_raw.get("forecast_qty")
            forecast_qty = Decimal("0") if forecast_raw is None else Decimal(str(forecast_raw))
            need_qty = Decimal(need_raw)
            gap_raw = line_raw.get("gap_qty")
            # Legacy pre-gap snapshots: derive gap from need − forecast.
            gap_qty = need_qty - forecast_qty if gap_raw is None else Decimal(str(gap_raw))
            lines.append(
                MicromarketSupplyOrderLine(
                    product_code=product_code,
                    need_qty=need_qty,
                    category=category,
                    name=name,
                    supplier_name=_optional_str(line_raw.get("supplier_name")),
                    last_buy_price=_optional_decimal(line_raw.get("last_buy_price")),
                    package_quantity=_optional_decimal(line_raw.get("package_quantity")),
                    supplier_product_name=_optional_str(line_raw.get("supplier_product_name")),
                    gap_qty=gap_qty,
                    forecast_qty=forecast_qty,
                ),
            )
        machines.append(
            MicromarketSupplyOrderMachine(
                machine_id=machine_id,
                lines=tuple(lines),
            ),
        )
    return MicromarketSupplyOrder(
        order_id=order_id,
        created_at=created_at,
        expected_arrival_at=expected_arrival_at,
        machines=tuple(machines),
    )


def _parse_line_category(value: object) -> SupplyOrderLineCategory:
    # Legacy pre-category snapshots: default 2 so list/download/ResolveLoadingNeed keep working.
    if value is None:
        return 2
    if value == 2 or value == "2":
        return 2
    if value == 3 or value == "3":
        return 3
    raise ValueError("category must be 2 or 3")


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _optional_decimal(value: object) -> Decimal | None:
    if isinstance(value, str) and value.strip():
        return Decimal(value)
    if isinstance(value, Decimal):
        return value
    return None


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketSupplyOrderStore(MicromarketSupplyOrderStore):
    collection: MicromarketSupplyOrderCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketSupplyOrderStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_supply_orders_collection,
            owner="MongoMicromarketSupplyOrderStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def save(self, order: MicromarketSupplyOrder) -> None:
        self.collection.replace_one(
            {"_id": order.order_id},
            _order_to_document(order),
            upsert=True,
        )

    @beartype
    def get(self, order_id: str) -> MicromarketSupplyOrder | None:
        document = self.collection.find_one({"_id": order_id})
        if document is None:
            return None
        return _order_from_document(document)

    @beartype
    def list_newest(self, *, limit: int | None = None) -> Sequence[MicromarketSupplyOrder]:
        cursor = self.collection.find({}).sort("created_at", DESCENDING)
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple(_order_from_document(document) for document in cursor)

    @beartype
    def delete(self, order_id: str) -> bool:
        result = self.collection.delete_one({"_id": order_id})
        deleted = getattr(result, "deleted_count", 0)
        return int(deleted) > 0
