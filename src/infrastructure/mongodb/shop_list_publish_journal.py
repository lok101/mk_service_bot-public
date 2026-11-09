from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, DESCENDING, MongoClient

from src.application.micromarket_loading.ports import ShopListPublishJournal
from src.application.micromarket_loading.shop_list_publish_journal import (
    JOURNAL_CAPACITY,
    ShopListIntendedLine,
    ShopListPublishEffects,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class ShopListPublishJournalCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def update_one(self, filter: dict[str, Any], update: dict[str, Any]) -> Any: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def find_one_and_delete(
        self, filter: dict[str, Any], *, sort: list[tuple[str, int]]
    ) -> Any: ...


@beartype
def _codes_to_list(codes: tuple[str, ...]) -> list[str]:
    return list(codes)


@beartype
def _codes_from_document(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


@beartype
def _effects_to_document(effects: ShopListPublishEffects) -> dict[str, Any]:
    return {
        "disabled_product_codes": _codes_to_list(effects.disabled_product_codes),
        "enabled_product_codes": _codes_to_list(effects.enabled_product_codes),
        "added_product_codes": _codes_to_list(effects.added_product_codes),
        "removed_product_codes": _codes_to_list(effects.removed_product_codes),
        "updated_product_codes": _codes_to_list(effects.updated_product_codes),
    }


@beartype
def _effects_from_document(document: dict[str, Any]) -> ShopListPublishEffects:
    return ShopListPublishEffects(
        disabled_product_codes=_codes_from_document(document.get("disabled_product_codes")),
        enabled_product_codes=_codes_from_document(document.get("enabled_product_codes")),
        added_product_codes=_codes_from_document(document.get("added_product_codes")),
        removed_product_codes=_codes_from_document(document.get("removed_product_codes")),
        updated_product_codes=_codes_from_document(document.get("updated_product_codes")),
    )


@beartype
def _intended_to_document(lines: tuple[ShopListIntendedLine, ...]) -> list[dict[str, Any]]:
    return [
        {
            "product_code": line.product_code,
            "price_rub": str(line.price_rub),
            "kit_group_id": line.kit_group_id,
            "availability_off": line.availability_off,
        }
        for line in lines
    ]


@beartype
def _intended_from_document(raw: object) -> tuple[ShopListIntendedLine, ...]:
    if not isinstance(raw, list):
        return ()
    lines: list[ShopListIntendedLine] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        product_code = item.get("product_code")
        price_raw = item.get("price_rub")
        kit_group_id = item.get("kit_group_id")
        availability_off = item.get("availability_off", False)
        if not isinstance(product_code, str):
            continue
        if not isinstance(price_raw, str):
            continue
        if not isinstance(kit_group_id, int):
            continue
        if not isinstance(availability_off, bool):
            continue
        lines.append(
            ShopListIntendedLine(
                product_code=product_code,
                price_rub=Decimal(price_raw),
                kit_group_id=kit_group_id,
                availability_off=availability_off,
            )
        )
    return tuple(lines)


@beartype
def _trigger_from_document(raw: object) -> ShopListPublishTrigger | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return ShopListPublishTrigger(raw)
    except ValueError:
        return None


@beartype
def _entry_to_document(entry: ShopListPublishJournalEntry) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": entry.publication_id,
        "machine_code": entry.machine_code,
        "status": entry.status.value,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "error_message": entry.error_message,
        **_effects_to_document(entry.effects),
        "intended_lines": _intended_to_document(entry.intended_lines),
        "baseline_lines": _intended_to_document(entry.baseline_lines),
    }
    if entry.trigger is not None:
        document["trigger"] = entry.trigger.value
    return document


@beartype
def _entry_from_document(document: dict[str, Any]) -> ShopListPublishJournalEntry:
    publication_id = document.get("_id")
    machine_code = document.get("machine_code")
    status_raw = document.get("status")
    created_at = document.get("created_at")
    updated_at = document.get("updated_at")
    error_raw = document.get("error_message", "")
    if not isinstance(publication_id, str):
        raise ValueError("publication_id must be str")
    if not isinstance(machine_code, str):
        raise ValueError("machine_code must be str")
    if not isinstance(status_raw, str):
        raise ValueError("status must be str")
    if not isinstance(created_at, datetime):
        raise ValueError("created_at must be datetime")
    if not isinstance(updated_at, datetime):
        raise ValueError("updated_at must be datetime")
    if not isinstance(error_raw, str):
        raise ValueError("error_message must be str")
    return ShopListPublishJournalEntry(
        publication_id=publication_id,
        machine_code=machine_code,
        status=ShopListPublishJournalStatus(status_raw),
        created_at=created_at,
        updated_at=updated_at,
        error_message=error_raw,
        trigger=_trigger_from_document(document.get("trigger")),
        effects=_effects_from_document(document),
        intended_lines=_intended_from_document(document.get("intended_lines")),
        baseline_lines=_intended_from_document(document.get("baseline_lines")),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoShopListPublishJournal(ShopListPublishJournal):
    collection: ShopListPublishJournalCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoShopListPublishJournal:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.shop_list_publish_journal_collection,
            owner="MongoShopListPublishJournal",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def append(self, entry: ShopListPublishJournalEntry) -> None:
        self.collection.replace_one(
            {"_id": entry.publication_id},
            _entry_to_document(entry),
            upsert=True,
        )
        while self.collection.count_documents({}) > JOURNAL_CAPACITY:
            self.collection.find_one_and_delete({}, sort=[("created_at", ASCENDING)])

    @beartype
    def update_by_publication_id(
        self,
        publication_id: str,
        *,
        status: ShopListPublishJournalStatus,
        now: datetime,
        error_message: str = "",
    ) -> None:
        self.collection.update_one(
            {"_id": publication_id},
            {
                "$set": {
                    "status": status.value,
                    "updated_at": now,
                    "error_message": error_message,
                }
            },
        )

    @beartype
    def list_newest(self, *, limit: int | None = None) -> Sequence[ShopListPublishJournalEntry]:
        cursor = self.collection.find({}).sort("created_at", DESCENDING)
        if limit is not None:
            cursor = cursor.limit(limit)
        return tuple(_entry_from_document(document) for document in cursor)
