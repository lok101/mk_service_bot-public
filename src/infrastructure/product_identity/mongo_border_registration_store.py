from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.product_identity.border_registration import BorderRegistration
from src.config.domain_product_identity import DomainProductIdentitySettings
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class BorderRegistrationCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Iterable[dict[str, Any]]: ...


@beartype
class MongoBorderRegistrationStore:
    def __init__(self, collection: BorderRegistrationCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongodb: MongoSettings,
        identity: DomainProductIdentitySettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoBorderRegistrationStore:
        collection = resolve_collection(
            mongodb,
            collection_name=identity.border_registration_collection,
            owner="MongoBorderRegistrationStore",
            client=client,
        )
        return cls(collection)

    @beartype
    def get(self, ms_code: str) -> BorderRegistration | None:
        document = self._collection.find_one({"_id": ms_code.strip()})
        if document is None:
            return None
        return BorderRegistration(
            ms_code=str(document["_id"]),
            ignored=bool(document.get("ignored", False)),
        )

    @beartype
    def save(self, registration: BorderRegistration) -> None:
        self._collection.replace_one(
            {"_id": registration.ms_code},
            {"_id": registration.ms_code, "ignored": registration.ignored},
            upsert=True,
        )

    @beartype
    def list_ignored(self) -> tuple[BorderRegistration, ...]:
        return tuple(
            BorderRegistration(ms_code=str(document["_id"]), ignored=True)
            for document in self._collection.find({"ignored": True})
        )

    @beartype
    def list_pending(self) -> tuple[BorderRegistration, ...]:
        return tuple(
            BorderRegistration(ms_code=str(document["_id"]), ignored=False)
            for document in self._collection.find({"ignored": False})
        )
