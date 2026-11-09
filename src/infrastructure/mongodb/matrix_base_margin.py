from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation.ports import MatrixBaseMarginStore
from src.config.mongodb import MongoSettings
from src.domain.matrix_pricing.formula import BaseMarginParams
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_GLOBAL_ID = "global"


@runtime_checkable
class MatrixBaseMarginCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
def _params_to_document(params: BaseMarginParams) -> dict[str, Any]:
    rounding = params.rounding_last_digits
    return {
        "_id": _GLOBAL_ID,
        "scale_price_min": str(params.scale_price_min),
        "scale_price_max": str(params.scale_price_max),
        "scale_rate_max": str(params.scale_rate_max),
        "scale_rate_min": str(params.scale_rate_min),
        "curvature": str(params.curvature),
        "margin_floor": str(params.margin_floor),
        "rounding_last_digits": (None if rounding is None else sorted(rounding)),
    }


@beartype
def _decimal_field(document: dict[str, Any], key: str) -> Decimal:
    raw = document.get(key)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be Decimal-compatible") from exc


@beartype
def _params_from_document(document: dict[str, Any]) -> BaseMarginParams:
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
    return BaseMarginParams(
        scale_price_min=_decimal_field(document, "scale_price_min"),
        scale_price_max=_decimal_field(document, "scale_price_max"),
        scale_rate_max=_decimal_field(document, "scale_rate_max"),
        scale_rate_min=_decimal_field(document, "scale_rate_min"),
        curvature=_decimal_field(document, "curvature"),
        margin_floor=_decimal_field(document, "margin_floor"),
        rounding_last_digits=rounding,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMatrixBaseMarginStore(MatrixBaseMarginStore):
    collection: MatrixBaseMarginCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMatrixBaseMarginStore:
        collection = resolve_collection(
            mongo,
            collection_name=mongo.matrix_base_margin_collection,
            owner="MongoMatrixBaseMarginStore",
            client=client,
        )
        return cls(collection=collection)

    @beartype
    def get(self) -> BaseMarginParams | None:
        document = self.collection.find_one({"_id": _GLOBAL_ID})
        if document is None:
            return None
        return _params_from_document(document)

    @beartype
    def save(self, params: BaseMarginParams) -> None:
        self.collection.replace_one(
            {"_id": _GLOBAL_ID},
            _params_to_document(params),
            upsert=True,
        )
