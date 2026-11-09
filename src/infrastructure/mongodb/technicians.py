from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data import Technician
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import TechnicianId
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class TechniciansCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _technician_to_document(technician: Technician) -> dict[str, Any]:
    return {
        "_id": technician.technician_id.value,
        "name": technician.name,
        "is_active": technician.is_active,
    }


@beartype
def _technician_from_document(document: dict[str, Any]) -> Technician:
    id_raw = document.get("_id", document.get("technician_id"))
    name = document.get("name")
    is_active = document.get("is_active")
    if not isinstance(id_raw, str):
        raise ValueError("technician_id must be str")
    if not isinstance(name, str):
        raise ValueError("name must be str")
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be bool")
    return Technician(
        technician_id=TechnicianId(id_raw),
        name=name,
        is_active=is_active,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoTechnicianStore:
    collection: TechniciansCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        master_data: MasterDataSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoTechnicianStore:
        collection = resolve_collection(
            mongo,
            collection_name=master_data.technicians_collection,
            owner="MongoTechnicianStore",
            client=client,
        )
        store = cls(collection=collection)
        store.ensure_indexes()
        return store

    @beartype
    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("is_active", 1)],
            name="technician_is_active",
        )

    @beartype
    def get(self, technician_id: TechnicianId) -> Technician | None:
        document = self.collection.find_one({"_id": technician_id.value})
        if document is None:
            return None
        return _technician_from_document(document)

    @beartype
    def upsert(self, technician: Technician) -> None:
        self.collection.replace_one(
            {"_id": technician.technician_id.value},
            _technician_to_document(technician),
            upsert=True,
        )

    @beartype
    def list_all(self) -> tuple[Technician, ...]:
        items: list[Technician] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_technician_from_document(document))
        items.sort(key=lambda technician: technician.technician_id.value)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.collection.count_documents({})) == 0
