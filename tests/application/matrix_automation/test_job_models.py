from __future__ import annotations

from src.application.matrix_automation.job_models import MatrixDeployJob


def test_started_job_stores_trigger_seed() -> None:
    job = MatrixDeployJob.started(
        job_id="job-1",
        started_at="2026-07-14T00:00:00Z",
        trigger="seed",
    )
    assert job.trigger == "seed"
    assert job.status is None
    assert job.finished_at is None


def test_started_job_default_trigger_is_cron() -> None:
    job = MatrixDeployJob.started(
        job_id="job-1",
        started_at="2026-07-14T00:00:00Z",
    )
    assert job.trigger == "cron"


def test_finalize_preserves_trigger() -> None:
    job = MatrixDeployJob.started(
        job_id="job-1",
        started_at="2026-07-14T00:00:00Z",
        trigger="seed",
    ).finalize(
        status="skipped",
        finished_at="2026-07-14T00:01:00Z",
        units=(),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )
    assert job.trigger == "seed"
    assert job.status == "skipped"
