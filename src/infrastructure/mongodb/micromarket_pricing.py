from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, DESCENDING, MongoClient

from src.application.micromarket_loading.ports import (
    MicromarketMachineMultiplierStore,
    MicromarketPriceChangeJournal,
    MicromarketPricingRulesStore,
    MicromarketProductMultiplierStore,
)
from src.application.micromarket_loading.pricing_stores import (
    MicromarketPriceChangeJournalEntry,
    PriceChangeOrigin,
)
from src.config.mongodb import MongoSettings
from src.domain.micromarket_pricing.formula import MicromarketPricingRules
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_GLOBAL_ID = "global"


@runtime_checkable
class _ReplaceFindCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def delete_one(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def insert_one(self, document: dict[str, Any], **kwargs: Any) -> Any: ...

    def create_index(self, keys: Any, **kwargs: Any) -> Any: ...


@beartype
def _decimal_field(document: dict[str, Any], key: str) -> Decimal:
    raw = document.get(key)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be Decimal-compatible") from exc


@beartype
def _rules_to_document(rules: MicromarketPricingRules) -> dict[str, Any]:
    rounding = rules.rounding_last_digits
    return {
        "_id": _GLOBAL_ID,
        "margin_percent": str(rules.margin_percent),
        "margin_floor": str(rules.margin_floor),
        "rounding_last_digits": None if rounding is None else sorted(rounding),
    }


@beartype
def _rules_from_document(document: dict[str, Any]) -> MicromarketPricingRules:
    rounding_raw = document.get("rounding_last_digits")
    rounding: frozenset[int] | None
    if rounding_raw is None:
        rounding = None
    elif isinstance(rounding_raw, list):
        if not all(isinstance(item, int) for item in rounding_raw):
            raise ValueError("rounding_last_digits must be list[int] or null")
        rounding = frozenset(rounding_raw)
    else:
        raise ValueError("rounding_last_digits must be list[int] or null")
    return MicromarketPricingRules(
        margin_percent=_decimal_field(document, "margin_percent"),
        margin_floor=_decimal_field(document, "margin_floor"),
        rounding_last_digits=rounding,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketPricingRulesStore(MicromarketPricingRulesStore):
    collection: _ReplaceFindCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketPricingRulesStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_pricing_rules_collection,
            owner="MongoMicromarketPricingRulesStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self) -> MicromarketPricingRules | None:
        document = self.collection.find_one({"_id": _GLOBAL_ID})
        if document is None:
            return None
        return _rules_from_document(document)

    @beartype
    def save(self, rules: MicromarketPricingRules) -> None:
        self.collection.replace_one(
            {"_id": _GLOBAL_ID},
            _rules_to_document(rules),
            upsert=True,
        )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketProductMultiplierStore(MicromarketProductMultiplierStore):
    collection: _ReplaceFindCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketProductMultiplierStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_product_multipliers_collection,
            owner="MongoMicromarketProductMultiplierStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, product_code: str) -> Decimal | None:
        document = self.collection.find_one({"_id": product_code})
        if document is None:
            return None
        return _decimal_field(document, "multiplier")

    @beartype
    def list_all(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for document in self.collection.find({}):
            code = str(document["_id"])
            out[code] = _decimal_field(document, "multiplier")
        return out

    @beartype
    def upsert(self, product_code: str, multiplier: Decimal) -> None:
        self.collection.replace_one(
            {"_id": product_code},
            {"_id": product_code, "multiplier": str(multiplier)},
            upsert=True,
        )

    @beartype
    def delete(self, product_code: str) -> None:
        self.collection.delete_one({"_id": product_code})


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketMachineMultiplierStore(MicromarketMachineMultiplierStore):
    collection: _ReplaceFindCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketMachineMultiplierStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_machine_multipliers_collection,
            owner="MongoMicromarketMachineMultiplierStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self, machine_id: str) -> Decimal | None:
        document = self.collection.find_one({"_id": machine_id})
        if document is None:
            return None
        return _decimal_field(document, "multiplier")

    @beartype
    def list_all(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for document in self.collection.find({}):
            mid = str(document["_id"])
            out[mid] = _decimal_field(document, "multiplier")
        return out

    @beartype
    def upsert(self, machine_id: str, multiplier: Decimal) -> None:
        self.collection.replace_one(
            {"_id": machine_id},
            {"_id": machine_id, "multiplier": str(multiplier)},
            upsert=True,
        )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketPriceChangeJournal(MicromarketPriceChangeJournal):
    collection: _ReplaceFindCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMicromarketPriceChangeJournal:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.micromarket_price_change_journal_collection,
            owner="MongoMicromarketPriceChangeJournal",
            client=client,
        )
        collection.create_index(
            [("machine_id", ASCENDING), ("at", DESCENDING)],
            name="machine_at_desc",
        )
        return cls(collection=collection)

    @beartype
    def append(self, entry: MicromarketPriceChangeJournalEntry) -> None:
        self.collection.insert_one(
            {
                "machine_id": entry.machine_id,
                "product_code": entry.product_code,
                "old_price_rub": (
                    None if entry.old_price_rub is None else str(entry.old_price_rub)
                ),
                "new_price_rub": str(entry.new_price_rub),
                "origin": entry.origin,
                "actor": entry.actor,
                "reason": entry.reason,
                "at": entry.at,
            },
        )

    @beartype
    def list_for_machine(
        self,
        machine_id: str,
        *,
        limit: int = 100,
    ) -> tuple[MicromarketPriceChangeJournalEntry, ...]:
        cursor = (
            self.collection.find({"machine_id": machine_id}).sort("at", DESCENDING).limit(limit)
        )
        entries: list[MicromarketPriceChangeJournalEntry] = []
        for document in cursor:
            old_raw = document.get("old_price_rub")
            at_raw = document["at"]
            at = at_raw if isinstance(at_raw, datetime) else datetime.now(UTC)
            origin = document["origin"]
            if origin not in ("calculated", "manual", "reset", "cutover"):
                raise ValueError(f"invalid journal origin: {origin}")
            typed_origin: PriceChangeOrigin = origin
            entries.append(
                MicromarketPriceChangeJournalEntry(
                    machine_id=str(document["machine_id"]),
                    product_code=str(document["product_code"]),
                    old_price_rub=None if old_raw is None else Decimal(str(old_raw)),
                    new_price_rub=_decimal_field(document, "new_price_rub"),
                    origin=typed_origin,
                    actor=str(document.get("actor", "")),
                    reason=document.get("reason"),
                    at=at,
                ),
            )
        return tuple(reversed(entries))
