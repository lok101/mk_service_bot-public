from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.form_inventory_policy import (
    FormInventoryPolicyLine,
    FormInventoryPolicyProfile,
    FormInventoryPolicyProfileId,
)
from src.config.mongodb import MongoSettings
from src.domain.quantities import QuantityInputMode
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_DEFAULT_COLLECTION = "form_inventory_policies"
_PROFILE_IDS = frozenset(
    {
        "coffee_loading",
        "coffee_revision",
        "technician_warehouse_coffee",
    }
)
_MODE_BY_VALUE = {mode.value: mode for mode in QuantityInputMode}


@runtime_checkable
class FormInventoryPolicyCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def find(self, filter: dict[str, Any]) -> Iterable[dict[str, Any]]: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
class MongoFormInventoryPolicyStore:
    def __init__(self, collection: FormInventoryPolicyCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: FormInventoryPolicyCollection,
    ) -> MongoFormInventoryPolicyStore:
        store = cls(collection)
        store._ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongodb: MongoSettings,
        *,
        collection_name: str = _DEFAULT_COLLECTION,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoFormInventoryPolicyStore:
        collection = resolve_collection(
            mongodb,
            collection_name=collection_name,
            owner="MongoFormInventoryPolicyStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def get_profile(
        self,
        profile_id: FormInventoryPolicyProfileId,
    ) -> FormInventoryPolicyProfile | None:
        document = self._collection.find_one({"_id": _profile_doc_id(profile_id)})
        if document is None:
            return None
        return _profile_from_document(document)

    @beartype
    def save_profile(self, profile: FormInventoryPolicyProfile) -> None:
        self._collection.replace_one(
            {"_id": _profile_doc_id(profile.profile_id)},
            {
                "_id": _profile_doc_id(profile.profile_id),
                "doc_kind": "profile",
                "profile_id": profile.profile_id,
                "input_mode": profile.input_mode.value,
                "allow_zero": profile.allow_zero,
                "apply_stock_range": profile.apply_stock_range,
                "allow_empty": profile.allow_empty,
            },
            upsert=True,
        )

    @beartype
    def get_line(
        self,
        profile_id: FormInventoryPolicyProfileId,
        domain_number: str,
    ) -> FormInventoryPolicyLine | None:
        document = self._collection.find_one(
            {"_id": _line_doc_id(profile_id, domain_number)},
        )
        if document is None:
            return None
        return _line_from_document(document)

    @beartype
    def upsert_line(
        self,
        profile_id: FormInventoryPolicyProfileId,
        line: FormInventoryPolicyLine,
    ) -> None:
        payload: dict[str, Any] = {
            "_id": _line_doc_id(profile_id, line.domain_number),
            "doc_kind": "line",
            "profile_id": profile_id,
            "domain_number": line.domain_number,
            "min_qty": str(line.min_qty),
            "max_qty": str(line.max_qty),
            "sort_order": int(line.sort_order),
            "form_label": line.form_label,
            "form_hint": line.form_hint,
        }
        if line.radio_n is not None:
            payload["radio_n"] = line.radio_n
        self._collection.replace_one(
            {"_id": payload["_id"]},
            payload,
            upsert=True,
        )

    @beartype
    def list_lines(
        self,
        profile_id: FormInventoryPolicyProfileId,
    ) -> tuple[FormInventoryPolicyLine, ...]:
        documents = self._collection.find(
            {"doc_kind": "line", "profile_id": profile_id},
        )
        lines = [_line_from_document(document) for document in documents]
        return tuple(
            sorted(lines, key=lambda line: (line.sort_order, line.domain_number)),
        )

    def _ensure_indexes(self) -> None:
        self._collection.create_index(
            [("doc_kind", 1), ("profile_id", 1), ("domain_number", 1)],
            name="policy_line_lookup",
        )


@beartype
def _profile_doc_id(profile_id: FormInventoryPolicyProfileId) -> str:
    return f"profile:{profile_id}"


@beartype
def _line_doc_id(profile_id: FormInventoryPolicyProfileId, domain_number: str) -> str:
    return f"line:{profile_id}:{domain_number}"


@beartype
def _parse_decimal(raw: object) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid decimal: {raw!r}") from error


@beartype
def _profile_from_document(document: dict[str, Any]) -> FormInventoryPolicyProfile:
    raw_id = str(document.get("profile_id", ""))
    if raw_id not in _PROFILE_IDS:
        raise ValueError(f"unknown policy profile id: {raw_id!r}")
    profile_id = cast(FormInventoryPolicyProfileId, raw_id)
    raw_mode = str(document.get("input_mode", ""))
    mode = _MODE_BY_VALUE.get(raw_mode)
    if mode is None:
        raise ValueError(f"unknown input_mode: {raw_mode!r}")
    return FormInventoryPolicyProfile(
        profile_id=profile_id,
        input_mode=mode,
        allow_zero=bool(document.get("allow_zero")),
        apply_stock_range=bool(document.get("apply_stock_range")),
        allow_empty=bool(document.get("allow_empty", True)),
    )


@beartype
def _line_from_document(document: dict[str, Any]) -> FormInventoryPolicyLine:
    raw_radio = document.get("radio_n")
    radio_n = int(raw_radio) if isinstance(raw_radio, int) else None
    raw_order = document.get("sort_order", 0)
    try:
        sort_order = int(raw_order)
    except (TypeError, ValueError):
        sort_order = 0
    return FormInventoryPolicyLine(
        domain_number=str(document["domain_number"]),
        min_qty=_parse_decimal(document.get("min_qty")),
        max_qty=_parse_decimal(document.get("max_qty")),
        radio_n=radio_n,
        sort_order=sort_order,
        form_label=str(document.get("form_label", "") or ""),
        form_hint=str(document.get("form_hint", "") or ""),
    )
