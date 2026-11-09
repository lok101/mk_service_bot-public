from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.snack_loading.ports import SnackLoadingRunRecord, SnackLoadingRunStore
from src.config.mongodb import MongoSettings
from src.domain.snack_loading.events import CellKey
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class SnackLoadingRunsCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


def _increments_to_docs(
    increments: tuple[tuple[CellKey, Decimal], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "machine_code": key[0],
            "logical_matrix_name": key[1],
            "line_number": key[2],
            "quantity": str(qty),
        }
        for key, qty in increments
    ]


def _increments_from_docs(
    rows: list[Any],
) -> tuple[tuple[CellKey, Decimal], ...]:
    out: list[tuple[CellKey, Decimal]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        machine = row.get("machine_code")
        matrix = row.get("logical_matrix_name")
        line = row.get("line_number")
        qty = row.get("quantity")
        if (
            isinstance(machine, str)
            and isinstance(matrix, str)
            and isinstance(line, int)
            and isinstance(qty, str)
        ):
            out.append(((machine, matrix, line), Decimal(qty)))
    return tuple(out)


@beartype
@dataclass(frozen=True, slots=True)
class MongoSnackLoadingRunStore(SnackLoadingRunStore):
    _collection: SnackLoadingRunsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: SnackLoadingRunsCollection,
    ) -> MongoSnackLoadingRunStore:
        return cls(_collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoSnackLoadingRunStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.snack_loading_runs_collection,
            owner="MongoSnackLoadingRunStore",
            client=client,
        )
        return cls.from_collection(cast(SnackLoadingRunsCollection, collection))

    @beartype
    def get(self, run_id: str) -> SnackLoadingRunRecord | None:
        doc = self._collection.find_one({"_id": run_id})
        if doc is None:
            return None
        increments_raw = doc.get("increments")
        raw_list = increments_raw if isinstance(increments_raw, list) else []
        increments = _increments_from_docs(raw_list)
        return SnackLoadingRunRecord(
            run_id=str(doc["_id"]),
            machine_code=str(doc["machine_code"]),
            move_id=str(doc["move_id"]),
            increments=increments,
            domain_applied=bool(doc.get("domain_applied", False)),
        )

    @beartype
    def save(self, record: SnackLoadingRunRecord) -> None:
        self._collection.replace_one(
            {"_id": record.run_id},
            {
                "_id": record.run_id,
                "run_id": record.run_id,
                "machine_code": record.machine_code,
                "move_id": record.move_id,
                "increments": _increments_to_docs(record.increments),
                "domain_applied": record.domain_applied,
            },
            upsert=True,
        )
