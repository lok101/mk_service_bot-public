from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.micromarket_loading.planogram import PriceOrigin
from src.application.micromarket_loading.ports import MicromarketPlanogramStore
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MicromarketPlanogramsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...


@beartype
def _line_to_document(line: MicromarketPlanogramLine) -> dict[str, Any]:
    document: dict[str, Any] = {
        "product_code": line.product_code,
        "target_qty": line.target_qty,
        "price_rub": str(line.price_rub),
        "active": line.active,
        "sort_order": line.sort_order,
        "kit_group_id": line.kit_group_id,
        "pending_exit": line.pending_exit,
        "price_origin": line.price_origin,
    }
    if line.domain_product_id is not None:
        document["domain_product_id"] = line.domain_product_id
    return document


@beartype
def _line_from_document(raw: dict[str, Any]) -> MicromarketPlanogramLine:
    product_code = raw.get("product_code")
    target_qty = raw.get("target_qty")
    price_raw = raw.get("price_rub")
    active = raw.get("active")
    sort_order = raw.get("sort_order")
    kit_group_raw = raw.get("kit_group_id")
    domain_product_raw = raw.get("domain_product_id")
    if not isinstance(product_code, str):
        raise ValueError("product_code must be str")
    if not isinstance(target_qty, int):
        raise ValueError("target_qty must be int")
    if not isinstance(active, bool):
        raise ValueError("active must be bool")
    if not isinstance(sort_order, int):
        raise ValueError("sort_order must be int")
    if kit_group_raw is None:
        kit_group_id: int | None = None
    elif isinstance(kit_group_raw, int):
        kit_group_id = kit_group_raw
    else:
        raise ValueError("kit_group_id must be int or None")
    if domain_product_raw is None:
        domain_product_id: str | None = None
    elif isinstance(domain_product_raw, str):
        domain_product_id = domain_product_raw
    else:
        raise ValueError("domain_product_id must be str or None")
    pending_exit_raw = raw.get("pending_exit", False)
    if not isinstance(pending_exit_raw, bool):
        raise ValueError("pending_exit must be bool")
    price_origin_raw = raw.get("price_origin", "manual")
    price_origin: PriceOrigin
    if price_origin_raw == "calculated":
        price_origin = "calculated"
    elif price_origin_raw == "manual":
        price_origin = "manual"
    else:
        raise ValueError("price_origin must be 'manual' or 'calculated'")
    try:
        price_rub = Decimal(str(price_raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("price_rub must be Decimal-compatible") from exc
    return MicromarketPlanogramLine(
        product_code=product_code,
        target_qty=target_qty,
        price_rub=price_rub,
        active=active,
        sort_order=sort_order,
        kit_group_id=kit_group_id,
        domain_product_id=domain_product_id,
        pending_exit=pending_exit_raw,
        price_origin=price_origin,
    )


@beartype
def _shelf_to_document(shelf: MicromarketPlanogramShelf) -> dict[str, Any]:
    return {
        "kit_group_id": shelf.kit_group_id,
        "sort_order": shelf.sort_order,
    }


@beartype
def _shelf_from_document(raw: object) -> MicromarketPlanogramShelf:
    if not isinstance(raw, dict):
        raise ValueError("shelf must be dict")
    kit_group_id = raw.get("kit_group_id")
    sort_order = raw.get("sort_order")
    if not isinstance(kit_group_id, int):
        raise ValueError("kit_group_id must be int")
    if not isinstance(sort_order, int):
        raise ValueError("sort_order must be int")
    return MicromarketPlanogramShelf(kit_group_id=kit_group_id, sort_order=sort_order)


@beartype
def _shelves_from_document(
    document: dict[str, Any],
) -> tuple[MicromarketPlanogramShelf, ...] | None:
    if "shelves" not in document:
        return None
    shelves_raw = document["shelves"]
    if not isinstance(shelves_raw, list):
        raise ValueError("shelves must be list")
    shelves: list[MicromarketPlanogramShelf] = []
    seen_kit_group_ids: set[int] = set()
    for item in shelves_raw:
        shelf = _shelf_from_document(item)
        if shelf.kit_group_id in seen_kit_group_ids:
            raise ValueError("duplicate kit_group_id in shelves")
        seen_kit_group_ids.add(shelf.kit_group_id)
        shelves.append(shelf)
    return tuple(shelves)


@beartype
def _planogram_to_document(planogram: MicromarketPlanogram) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": planogram.machine_code,
        "lines": [_line_to_document(line) for line in planogram.lines],
        "updated_at": planogram.updated_at,
        "shop_list_status": planogram.shop_list_status.value,
        "shop_list_error": planogram.shop_list_error,
        "shop_list_publication_id": planogram.shop_list_publication_id,
        "shop_list_catch_up_requested": planogram.shop_list_catch_up_requested,
    }
    if planogram.shelves is not None:
        document["shelves"] = [_shelf_to_document(shelf) for shelf in planogram.shelves]
    return document


@beartype
def _planogram_from_document(document: dict[str, Any]) -> MicromarketPlanogram:
    machine_code = document.get("_id", document.get("machine_code"))
    lines_raw = document.get("lines")
    updated_at = document.get("updated_at")
    if not isinstance(machine_code, str):
        raise ValueError("machine_code must be str")
    if not isinstance(lines_raw, list):
        raise ValueError("lines must be list")
    if not isinstance(updated_at, datetime):
        raise ValueError("updated_at must be datetime")
    lines = tuple(_line_from_document(item) for item in lines_raw if isinstance(item, dict))
    status_raw = document.get("shop_list_status", ShopListPublishStatus.UNPUBLISHED.value)
    if not isinstance(status_raw, str):
        raise ValueError("shop_list_status must be str")
    try:
        shop_list_status = ShopListPublishStatus(status_raw)
    except ValueError as exc:
        raise ValueError(f"unknown shop_list_status: {status_raw}") from exc
    error_raw = document.get("shop_list_error", "")
    publication_raw = document.get("shop_list_publication_id", "")
    if not isinstance(error_raw, str):
        raise ValueError("shop_list_error must be str")
    if not isinstance(publication_raw, str):
        raise ValueError("shop_list_publication_id must be str")
    shelves = _shelves_from_document(document)
    return MicromarketPlanogram(
        machine_code=machine_code,
        lines=lines,
        updated_at=updated_at,
        shop_list_status=shop_list_status,
        shop_list_error=error_raw,
        shop_list_publication_id=publication_raw,
        shop_list_catch_up_requested=bool(document.get("shop_list_catch_up_requested", False)),
        shelves=shelves,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketPlanogramStore(MicromarketPlanogramStore):
    collection: MicromarketPlanogramsCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketPlanogramStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_planograms_collection,
            owner="MongoMicromarketPlanogramStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, machine_code: str) -> MicromarketPlanogram | None:
        document = self.collection.find_one({"_id": machine_code})
        if document is None:
            return None
        return _planogram_from_document(document)

    @beartype
    def upsert(self, planogram: MicromarketPlanogram) -> None:
        self.collection.replace_one(
            {"_id": planogram.machine_code},
            _planogram_to_document(planogram),
            upsert=True,
        )

    @beartype
    def list_all(self) -> Sequence[MicromarketPlanogram]:
        rows = self.collection.find({})
        result: list[MicromarketPlanogram] = []
        for document in rows:
            if isinstance(document, dict):
                result.append(_planogram_from_document(document))
        return tuple(result)
