from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, DESCENDING, MongoClient

from src.application.matrix_automation import (
    BlockedMatrixEntry,
    BlockedProductRef,
    MatrixDeployJob,
    MatrixDeployJobRepository,
    MatrixDeployJobUnit,
    ProductSwapBlockedLine,
    SkuStats,
    StrongPriceIncreaseLine,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MatrixDeployJobsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _started_document(job: MatrixDeployJob) -> dict[str, Any]:
    return {
        "_id": job.job_id,
        "started_at": job.started_at,
        "finished_at": None,
        "status": None,
        "trigger": job.trigger,
        "units": [],
        "blocked_matrices": [],
    }


@beartype
def _sku_stats_document(stats: SkuStats) -> dict[str, int]:
    return {
        "applied": stats.applied,
        "kept_previous": stats.kept_previous,
        "skipped_no_baseline": stats.skipped_no_baseline,
        "strong_price_increase": stats.strong_price_increase,
        "blocked_empty": stats.blocked_empty,
        "product_swap_blocked": stats.product_swap_blocked,
    }


@beartype
def _strong_line_document(line: StrongPriceIncreaseLine) -> dict[str, object]:
    return {
        "machine_code": line.machine_code,
        "line_number": line.line_number,
        "product_code": line.product_code,
        "baseline": line.baseline,
        "deploy_price": line.deploy_price,
        "increase_pct": line.increase_pct,
    }


@beartype
def _swap_line_document(line: ProductSwapBlockedLine) -> dict[str, object]:
    return {
        "machine_code": line.machine_code,
        "line_number": line.line_number,
        "current_product": line.current_product,
        "desired_product": line.desired_product,
        "reason": line.reason,
    }


@beartype
def _product_document(product: BlockedProductRef) -> dict[str, object]:
    return {
        "product_name": product.product_name,
        "product_code": product.product_code,
    }


@beartype
def _blocked_matrix_document(entry: BlockedMatrixEntry) -> dict[str, object]:
    return {
        "logical_matrix_name": entry.logical_matrix_name,
        "deploy_reason": entry.deploy_reason,
        "detail": entry.detail,
        "products": [_product_document(product) for product in entry.products],
        "machine_codes": list(entry.machine_codes),
    }


@beartype
def _unit_document(unit: MatrixDeployJobUnit) -> dict[str, object]:
    document: dict[str, object] = {
        "logical_matrix_name": unit.logical_matrix_name,
        "machine_code": unit.machine_code,
        "deploy_status": unit.deploy_status,
        "deploy_reason": unit.deploy_reason,
    }
    if unit.sku_stats is not None:
        document["sku_stats"] = _sku_stats_document(unit.sku_stats)
        document["strong_price_increase_lines"] = [
            _strong_line_document(line) for line in unit.strong_price_increase_lines
        ]
        document["product_swap_blocked_lines"] = [
            _swap_line_document(line) for line in unit.product_swap_blocked_lines
        ]
    return document


@beartype
def _terminal_fields(job: MatrixDeployJob) -> dict[str, object]:
    assert job.status is not None
    assert job.finished_at is not None
    return {
        "finished_at": job.finished_at,
        "status": job.status,
        "auto_sync_disabled_matrices": job.auto_sync_disabled_matrices,
        "units": [_unit_document(unit) for unit in job.units],
        "blocked_matrices": [_blocked_matrix_document(entry) for entry in job.blocked_matrices],
    }


@beartype
@dataclass(slots=True)
class MongoMatrixDeployJobRepository(MatrixDeployJobRepository):
    collection: MatrixDeployJobsCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: MatrixDeployJobsCollection,
    ) -> MongoMatrixDeployJobRepository:
        return cls(collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMatrixDeployJobRepository:
        collection = resolve_collection(
            settings,
            collection_name="matrix_deploy_jobs",
            owner="MongoMatrixDeployJobRepository",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("started_at", DESCENDING)],
            name="matrix_deploy_jobs_started_at_desc",
        )
        self.collection.create_index(
            [("status", ASCENDING), ("finished_at", ASCENDING)],
            name="matrix_deploy_jobs_status_finished_at",
        )

    @beartype
    def insert(self, job: MatrixDeployJob) -> None:
        self.collection.insert_one(_started_document(job))

    @beartype
    def finalize(self, job: MatrixDeployJob) -> None:
        if job.status is None or job.finished_at is None:
            raise RuntimeError(f"Matrix job {job.job_id} is not terminal")
        result = self.collection.update_one(
            {"_id": job.job_id, "status": None, "finished_at": None},
            {"$set": _terminal_fields(job)},
        )
        if result.matched_count != 1:
            raise RuntimeError(f"Matrix job {job.job_id} was not an orphan")
