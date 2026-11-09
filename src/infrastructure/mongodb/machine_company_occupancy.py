from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancy,
    MachineCompanyOccupancyStore,
)
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class MachineCompanyOccupancyCollection(Protocol):
    def insert_many(self, documents: list[dict[str, Any]], **kwargs: Any) -> object: ...

    def delete_many(self, filter: dict[str, Any]) -> object: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _occupancy_to_document(interval: MachineCompanyOccupancy) -> dict[str, Any]:
    document: dict[str, Any] = {
        "machine_id": interval.machine_id.value,
        "company_id": interval.company_id,
        "valid_from": _as_utc(interval.valid_from),
        "valid_to": None if interval.valid_to is None else _as_utc(interval.valid_to),
    }
    return document


@beartype
def _occupancy_from_document(document: dict[str, Any]) -> MachineCompanyOccupancy:
    machine_id = document.get("machine_id")
    company_id = document.get("company_id")
    valid_from = document.get("valid_from")
    valid_to = document.get("valid_to")
    if (
        not isinstance(machine_id, str)
        or not isinstance(company_id, int)
        or isinstance(company_id, bool)
        or not isinstance(valid_from, datetime)
    ):
        raise ValueError("occupancy document has invalid shape")
    if valid_to is not None and not isinstance(valid_to, datetime):
        raise ValueError("occupancy valid_to must be datetime or None")
    return MachineCompanyOccupancy(
        machine_id=MachineId(machine_id),
        company_id=company_id,
        valid_from=_as_utc(valid_from),
        valid_to=None if valid_to is None else _as_utc(valid_to),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMachineCompanyOccupancyStore(MachineCompanyOccupancyStore):
    _collection: MachineCompanyOccupancyCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: MachineCompanyOccupancyCollection,
    ) -> MongoMachineCompanyOccupancyStore:
        store = cls(_collection=collection)
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMachineCompanyOccupancyStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.machine_company_occupancy_collection,
            owner="MongoMachineCompanyOccupancyStore",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("machine_id", ASCENDING), ("valid_from", ASCENDING)],
            unique=True,
            name="machine_company_occupancy_unique",
        )

    @beartype
    def replace_for_machine(
        self,
        machine_id: MachineId,
        intervals: Sequence[MachineCompanyOccupancy],
    ) -> None:
        self._collection.delete_many({"machine_id": machine_id.value})
        if not intervals:
            return
        self._collection.insert_many([_occupancy_to_document(item) for item in intervals])

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[MachineCompanyOccupancy, ...]:
        cursor = self._collection.find(
            {"machine_id": machine_id.value},
            sort=[("valid_from", ASCENDING)],
        )
        return tuple(_occupancy_from_document(document) for document in cursor)
