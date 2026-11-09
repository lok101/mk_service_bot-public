from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation import MatrixDeployJob
from src.application.matrix_automation.ports import MatrixWorkerStatusRepository
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class MatrixWorkerStatusCollection(Protocol):
    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
@dataclass(slots=True)
class MongoMatrixWorkerStatusRepository(MatrixWorkerStatusRepository):
    collection: MatrixWorkerStatusCollection

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: MatrixWorkerStatusCollection,
    ) -> MongoMatrixWorkerStatusRepository:
        return cls(collection=collection)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoMatrixWorkerStatusRepository:
        collection = resolve_collection(
            settings,
            collection_name="matrix_worker_status",
            owner="MongoMatrixWorkerStatusRepository",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.collection.update_one(
            {"_id": "worker"},
            {"$set": {"last_heartbeat_at": at, "worker_enabled": enabled}},
            upsert=True,
        )

    @beartype
    def record_terminal_job(self, job: MatrixDeployJob) -> None:
        if job.status is None or job.finished_at is None:
            raise RuntimeError(f"Matrix job {job.job_id} is not terminal")
        fields: dict[str, object] = {
            "last_job_id": job.job_id,
            "last_job_status": job.status,
        }
        if job.status == "completed":
            fields["last_successful_job_at"] = job.finished_at
        self.collection.update_one(
            {"_id": "worker"},
            {"$set": fields},
            upsert=True,
        )
