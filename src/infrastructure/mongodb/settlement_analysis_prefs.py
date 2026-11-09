from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.technician_settlement.analysis_prefs import SettlementAnalysisPrefs
from src.config.mongodb import MongoSettings
from src.config.settlement_analysis import SettlementAnalysisSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class SettlementAnalysisPrefsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


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
def prefs_to_document(
    telegram_user_id: int,
    prefs: SettlementAnalysisPrefs,
    *,
    updated_at: datetime,
) -> dict[str, Any]:
    return {
        "_id": telegram_user_id,
        "telegram_user_id": telegram_user_id,
        "unit_prices": {code: _decimal_to_str(price) for code, price in prefs.unit_prices.items()},
        "recoverable_product_codes": sorted(prefs.recoverable_product_codes),
        "allowed_loss_pct": _decimal_to_str(prefs.allowed_loss_pct),
        "updated_at": _as_utc(updated_at),
    }


@beartype
def prefs_from_document(document: dict[str, Any]) -> SettlementAnalysisPrefs:
    unit_prices_raw = document.get("unit_prices")
    recoverable_raw = document.get("recoverable_product_codes")
    allowed_loss_raw = document.get("allowed_loss_pct")
    if not isinstance(unit_prices_raw, dict):
        raise ValueError("unit_prices must be a dict")
    if not isinstance(recoverable_raw, list):
        raise ValueError("recoverable_product_codes must be a list")
    unit_prices: dict[str, Decimal] = {}
    for code, price in unit_prices_raw.items():
        if not isinstance(code, str):
            raise ValueError("unit_prices keys must be str")
        unit_prices[code] = _decimal_from_document(price)
    recoverable: list[str] = []
    for code in recoverable_raw:
        if not isinstance(code, str):
            raise ValueError("recoverable_product_codes items must be str")
        recoverable.append(code)
    return SettlementAnalysisPrefs(
        unit_prices=unit_prices,
        recoverable_product_codes=frozenset(recoverable),
        allowed_loss_pct=_decimal_from_document(allowed_loss_raw),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoSettlementAnalysisPrefsStore:
    _collection: SettlementAnalysisPrefsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SettlementAnalysisPrefsCollection,
    ) -> MongoSettlementAnalysisPrefsStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        settlement_analysis: SettlementAnalysisSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoSettlementAnalysisPrefsStore:
        collection = resolve_collection(
            mongo,
            collection_name=settlement_analysis.prefs_collection,
            owner="MongoSettlementAnalysisPrefsStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def get(self, telegram_user_id: int) -> SettlementAnalysisPrefs:
        document = self._collection.find_one({"_id": telegram_user_id})
        if document is None:
            return SettlementAnalysisPrefs.empty()
        return prefs_from_document(document)

    @beartype
    def save(self, telegram_user_id: int, prefs: SettlementAnalysisPrefs) -> None:
        document = prefs_to_document(
            telegram_user_id,
            prefs,
            updated_at=datetime.now(UTC),
        )
        self._collection.replace_one(
            {"_id": telegram_user_id},
            document,
            upsert=True,
        )
