from __future__ import annotations

import mongomock
import pytest

from src.application.matrix_automation import MatrixDeployJob
from src.infrastructure.matrix_automation.mongo_worker_status import (
    MongoMatrixWorkerStatusRepository,
)

_HEARTBEAT = "2026-07-10T00:01:00+00:00"
_FINISHED = "2026-07-10T00:05:00+00:00"
_PREVIOUS_SUCCESS = "2026-07-09T00:05:00+00:00"


@pytest.fixture
def collection() -> mongomock.collection.Collection:
    return mongomock.MongoClient().db.matrix_worker_status


def test_record_heartbeat_upserts_single_worker_document(collection) -> None:
    repository = MongoMatrixWorkerStatusRepository(collection)

    repository.record_heartbeat(at=_HEARTBEAT, enabled=True)

    assert collection.find_one({"_id": "worker"}) == {
        "_id": "worker",
        "last_heartbeat_at": _HEARTBEAT,
        "worker_enabled": True,
    }

    repository.record_heartbeat(at="2026-07-10T00:02:00+00:00", enabled=False)

    assert collection.count_documents({}) == 1
    document = collection.find_one({"_id": "worker"})
    assert document is not None
    assert document["last_heartbeat_at"] == "2026-07-10T00:02:00+00:00"
    assert document["worker_enabled"] is False


def test_record_terminal_completed_sets_last_successful_job_at(collection) -> None:
    repository = MongoMatrixWorkerStatusRepository(collection)
    job = MatrixDeployJob.started(job_id="job-1", started_at="2026-07-10T00:00:00+00:00").finalize(
        status="completed",
        finished_at=_FINISHED,
        units=(),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )

    repository.record_terminal_job(job)

    document = collection.find_one({"_id": "worker"})
    assert document is not None
    assert document["last_job_id"] == "job-1"
    assert document["last_job_status"] == "completed"
    assert document["last_successful_job_at"] == _FINISHED


def test_record_terminal_failed_keeps_previous_last_successful_job_at(collection) -> None:
    repository = MongoMatrixWorkerStatusRepository(collection)
    collection.insert_one(
        {
            "_id": "worker",
            "last_heartbeat_at": _HEARTBEAT,
            "worker_enabled": True,
            "last_successful_job_at": _PREVIOUS_SUCCESS,
            "last_job_id": "job-0",
            "last_job_status": "completed",
        }
    )
    failed = MatrixDeployJob.started(
        job_id="job-1",
        started_at="2026-07-10T00:00:00+00:00",
    ).finalize(
        status="failed",
        finished_at=_FINISHED,
        units=(),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )

    repository.record_terminal_job(failed)

    document = collection.find_one({"_id": "worker"})
    assert document is not None
    assert document["last_job_id"] == "job-1"
    assert document["last_job_status"] == "failed"
    assert document["last_successful_job_at"] == _PREVIOUS_SUCCESS
