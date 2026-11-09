from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.product_identity import (
    DomainProduct,
    DomainProductConflict,
    DomainProductKind,
    catalog_codes_of,
)
from src.config.domain_product_identity import DomainProductIdentitySettings
from src.config.mongodb import MongoSettings
from src.domain.product_catalog import ProductUnit
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

_UNIT_BY_NAME = {unit.name: unit for unit in ProductUnit}


@runtime_checkable
class DomainProductCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Iterable[dict[str, Any]]: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
class MongoDomainProductStore:
    def __init__(self, collection: DomainProductCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_collection(cls, collection: DomainProductCollection) -> MongoDomainProductStore:
        store = cls(collection)
        store._ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongodb: MongoSettings,
        identity: DomainProductIdentitySettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoDomainProductStore:
        collection = resolve_collection(
            mongodb,
            collection_name=identity.collection,
            owner="MongoDomainProductStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def insert(self, product: DomainProduct) -> None:
        self._reject_conflicts(product, skip_id=None)
        try:
            self._collection.insert_one(_to_document(product))
        except DuplicateKeyError as error:
            self._raise_duplicate(product, skip_id=None, error=error)

    @beartype
    def save(self, product: DomainProduct) -> None:
        self._reject_conflicts(product, skip_id=product.domain_product_id)
        try:
            self._collection.replace_one(
                {"_id": product.domain_product_id},
                _to_document(product),
                upsert=True,
            )
        except DuplicateKeyError as error:
            self._raise_duplicate(product, skip_id=product.domain_product_id, error=error)

    @beartype
    def get(self, domain_product_id: str) -> DomainProduct | None:
        document = self._collection.find_one({"_id": domain_product_id})
        if document is None:
            return None
        return _from_document(document)

    @beartype
    def get_by_number(self, number: str) -> DomainProduct | None:
        document = self._collection.find_one({"number": number})
        if document is None:
            return None
        return _from_document(document)

    @beartype
    def get_by_catalog_code(self, catalog_code: str) -> DomainProduct | None:
        document = self._collection.find_one(
            {
                "$or": [
                    {"catalog_code": catalog_code},
                    {"extra_catalog_codes": catalog_code},
                    {"legacy_ms_code": catalog_code},
                ]
            }
        )
        if document is None:
            return None
        return _from_document(document)

    @beartype
    def list_visible(self) -> tuple[DomainProduct, ...]:
        return tuple(
            _from_document(document)
            for document in self._collection.find({"hidden": {"$ne": True}})
        )

    @beartype
    def numbers(self) -> tuple[str, ...]:
        return tuple(str(document["number"]) for document in self._collection.find({}))

    def _ensure_indexes(self) -> None:
        self._collection.create_index("number", unique=True, name="number_unique")
        self._collection.create_index(
            "catalog_code",
            unique=True,
            name="catalog_code_unique",
            partialFilterExpression={
                "catalog_code": {"$exists": True, "$type": "string"},
            },
        )
        self._collection.create_index(
            "extra_catalog_codes",
            unique=True,
            name="extra_catalog_codes_unique",
            partialFilterExpression={
                "extra_catalog_codes": {"$exists": True, "$type": "array"},
            },
        )
        self._collection.create_index(
            "legacy_ms_code",
            unique=True,
            name="legacy_ms_code_unique",
            partialFilterExpression={
                "legacy_ms_code": {"$exists": True, "$type": "string"},
            },
        )

    def _reject_conflicts(self, product: DomainProduct, *, skip_id: str | None) -> None:
        number_holder = self.get_by_number(product.number)
        if number_holder is not None and number_holder.domain_product_id != skip_id:
            raise DomainProductConflict("number")
        codes = list(catalog_codes_of(product))
        if product.legacy_ms_code:
            codes.append(product.legacy_ms_code)
        for code in codes:
            code_holder = self.get_by_catalog_code(code)
            if code_holder is not None and code_holder.domain_product_id != skip_id:
                raise DomainProductConflict("catalog_code")

    def _raise_duplicate(
        self,
        product: DomainProduct,
        *,
        skip_id: str | None,
        error: DuplicateKeyError,
    ) -> NoReturn:
        number_holder = self.get_by_number(product.number)
        if number_holder is not None and number_holder.domain_product_id != skip_id:
            raise DomainProductConflict("number") from error
        codes = list(catalog_codes_of(product))
        if product.legacy_ms_code:
            codes.append(product.legacy_ms_code)
        for code in codes:
            code_holder = self.get_by_catalog_code(code)
            if code_holder is not None and code_holder.domain_product_id != skip_id:
                raise DomainProductConflict("catalog_code") from error
        raise error


@beartype
def _to_document(product: DomainProduct) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": product.domain_product_id,
        "number": product.number,
        "name": product.name,
        "hidden": product.hidden,
        "kind": product.kind,
    }
    if product.catalog_code is not None:
        document["catalog_code"] = product.catalog_code
    if product.extra_catalog_codes:
        document["extra_catalog_codes"] = list(product.extra_catalog_codes)
    if product.legacy_ms_code is not None:
        document["legacy_ms_code"] = product.legacy_ms_code
    if product.unit is not None:
        document["unit"] = product.unit.name
    if product.pack_size is not None:
        document["pack_size"] = str(product.pack_size)
    return document


@beartype
def _parse_unit(raw: object) -> ProductUnit | None:
    if not isinstance(raw, str):
        return None
    return _UNIT_BY_NAME.get(raw.strip().upper())


@beartype
def _parse_pack_size(raw: object) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation, ValueError:
        return None
    return value


@beartype
def _from_document(document: dict[str, Any]) -> DomainProduct:
    raw_code = document.get("catalog_code")
    catalog_code = raw_code if isinstance(raw_code, str) else None
    raw_kind = document.get("kind", "micromarket")
    kind: DomainProductKind = (
        raw_kind
        if raw_kind in ("micromarket", "coffee_ingredient", "coffee_drink")
        else "micromarket"
    )
    raw_extra = document.get("extra_catalog_codes") or ()
    extra = tuple(str(item) for item in raw_extra if isinstance(item, str) and item)
    raw_legacy = document.get("legacy_ms_code")
    legacy = raw_legacy if isinstance(raw_legacy, str) else None
    return DomainProduct(
        domain_product_id=str(document["_id"]),
        number=str(document["number"]),
        name=str(document["name"]),
        catalog_code=catalog_code,
        hidden=bool(document.get("hidden")),
        kind=kind,
        extra_catalog_codes=extra,
        legacy_ms_code=legacy,
        unit=_parse_unit(document.get("unit")),
        pack_size=_parse_pack_size(document.get("pack_size")),
    )
