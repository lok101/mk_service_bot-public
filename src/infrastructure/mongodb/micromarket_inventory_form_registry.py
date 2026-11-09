from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.micromarket_loading.ports import (
    MicromarketInventoryFormMode,
    MicromarketInventoryFormRegistry,
    RegisteredMicromarketInventoryForm,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class MicromarketInventoryFormRegistryCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...


@beartype
@dataclass(frozen=True, slots=True)
class MongoMicromarketInventoryFormRegistry(MicromarketInventoryFormRegistry):
    _collection: MicromarketInventoryFormRegistryCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: MicromarketInventoryFormRegistryCollection,
    ) -> MongoMicromarketInventoryFormRegistry:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMicromarketInventoryFormRegistry:
        collection = resolve_collection(
            settings,
            collection_name=settings.micromarket_inventory_form_registry_collection,
            owner="MongoMicromarketInventoryFormRegistry",
            client=client,
        )
        return cls.from_collection(
            cast(MicromarketInventoryFormRegistryCollection, collection),
        )

    @beartype
    def get(
        self,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        fingerprint: str,
    ) -> RegisteredMicromarketInventoryForm | None:
        document = self._collection.find_one(
            {
                "machine_code": machine_code,
                "mode": mode,
                "fingerprint": fingerprint,
            },
        )
        if document is None:
            return None
        return RegisteredMicromarketInventoryForm(
            form_id=str(document["form_id"]),
            form_url=str(document["form_url"]),
        )

    @beartype
    def put(
        self,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        fingerprint: str,
        *,
        form_id: str,
        form_url: str,
    ) -> None:
        self._collection.replace_one(
            {
                "machine_code": machine_code,
                "mode": mode,
                "fingerprint": fingerprint,
            },
            {
                "machine_code": machine_code,
                "mode": mode,
                "fingerprint": fingerprint,
                "form_id": form_id,
                "form_url": form_url,
            },
            upsert=True,
        )
