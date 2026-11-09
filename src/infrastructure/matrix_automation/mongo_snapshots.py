from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation import PriceSnapshotDocument, SnapshotLineRecord
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class MatrixPriceSnapshotsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def find(
        self,
        filter: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> Any: ...


@beartype
def _document_to_snapshot(document: dict[str, Any]) -> PriceSnapshotDocument:
    raw_lines = document.get("lines", [])
    lines = tuple(
        SnapshotLineRecord(
            line_number=int(line["line_number"]),
            product_code=line.get("product_code"),
            product_name=str(line["product_name"]),
            capacity=int(line["capacity"]),
            purchase_price=line.get("purchase_price"),
            calculated_price=line.get("calculated_price"),
            deploy_price=str(line["deploy_price"]),
            outcome=line["outcome"],
            reason=line.get("reason"),
            strong_price_increase=bool(line.get("strong_price_increase", False)),
        )
        for line in raw_lines
    )
    return PriceSnapshotDocument(
        job_id=str(document["job_id"]),
        machine_code=str(document["machine_code"]),
        logical_matrix_name=str(document["logical_matrix_name"]),
        recorded_at=str(document["recorded_at"]),
        lines=lines,
    )


@beartype
def snapshot_to_document(document: PriceSnapshotDocument) -> dict[str, Any]:
    return {
        "job_id": document.job_id,
        "machine_code": document.machine_code,
        "logical_matrix_name": document.logical_matrix_name,
        "recorded_at": document.recorded_at,
        "lines": [
            {
                "line_number": line.line_number,
                "product_code": line.product_code,
                "product_name": line.product_name,
                "capacity": line.capacity,
                "purchase_price": line.purchase_price,
                "calculated_price": line.calculated_price,
                "deploy_price": line.deploy_price,
                "outcome": line.outcome,
                "reason": line.reason,
                "strong_price_increase": line.strong_price_increase,
            }
            for line in document.lines
        ],
    }


@beartype
@dataclass(slots=True)
class MongoMatrixPriceSnapshotStore:
    _collection: MatrixPriceSnapshotsCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMatrixPriceSnapshotStore:
        collection = resolve_collection(
            settings,
            collection_name="matrix_price_snapshots",
            owner="MongoMatrixPriceSnapshotStore",
            client=client,
        )
        return cls(_collection=collection)

    @beartype
    def save(self, document: PriceSnapshotDocument) -> None:
        self._collection.insert_one(snapshot_to_document(document))

    @beartype
    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        raw_document = self._collection.find(
            {
                "machine_code": machine_code,
                "logical_matrix_name": logical_matrix_name,
            },
            sort=[("recorded_at", -1)],
        )
        for _ in raw_document:
            return True
        return False

    @beartype
    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        cursor = self._collection.find(
            {
                "machine_code": machine_code,
                "logical_matrix_name": logical_matrix_name,
            },
            sort=[("recorded_at", -1)],
        )
        for raw_document in cursor:
            if not isinstance(raw_document, dict):
                continue
            snapshot = _document_to_snapshot(raw_document)
            if any(line.line_number == line_number for line in snapshot.lines):
                return snapshot
        return None

    @beartype
    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        cursor = self._collection.find(
            {"machine_code": machine_code},
            sort=[("recorded_at", -1)],
        )
        latest_by_matrix: dict[str, PriceSnapshotDocument] = {}
        for raw_document in cursor:
            if not isinstance(raw_document, dict):
                continue
            snapshot = _document_to_snapshot(raw_document)
            if snapshot.logical_matrix_name in latest_by_matrix:
                continue
            latest_by_matrix[snapshot.logical_matrix_name] = snapshot
        return tuple(latest_by_matrix[name] for name in sorted(latest_by_matrix))
