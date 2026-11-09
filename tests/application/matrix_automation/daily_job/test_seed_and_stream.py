from __future__ import annotations

import inspect
from decimal import Decimal

from src.application.matrix_automation.daily_job import RunDailyMatrixDeployJob
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixParseState,
)

from .fakes import (
    _build,
    _Clock,
    _Deployer,
    _JobRepo,
    _Logger,
    _matrix,
    _Notifier,
    _result,
    _runner,
    _SnapshotStore,
    _state,
    _StatusRepo,
    _Sync,
)


class _RecordingBuildWithSeedFlag:
    def __init__(self, result: BuildMatrixDeployResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult:
        self.calls.append({"job_id": job_id, "seed_only": seed_only})
        return self._result


def test_daily_job_seed_writes_trigger_seed_and_passes_seed_only() -> None:
    """happy: seed job insert.trigger=seed; run_build(..., seed_only=True)."""
    build = _RecordingBuildWithSeedFlag(BuildMatrixDeployResult(payloads=(), skipped_units=()))
    job_repo = _JobRepo()
    runner = RunDailyMatrixDeployJob(
        matrix_sync=_Sync(_state()),
        run_build=build,
        deployer=_Deployer(()),
        job_repository=job_repo,
        snapshot_store=_SnapshotStore(),
        status_repository=_StatusRepo(),
        notifier=_Notifier(),
        clock=_Clock(["2026-07-14T00:00:00Z", "2026-07-14T00:01:00Z"]),
        id_factory=lambda: "job-seed",
        logger=_Logger(),
        seed_only=True,
        trigger="seed",
    )
    finished = runner.run()
    assert job_repo.inserted[0].trigger == "seed"
    assert finished.trigger == "seed"
    assert build.calls == [{"job_id": "job-seed", "seed_only": True}]


def test_daily_job_default_trigger_cron_and_seed_only_false() -> None:
    """edge: nightly defaults — trigger cron, seed_only False."""
    build = _RecordingBuildWithSeedFlag(BuildMatrixDeployResult(payloads=(), skipped_units=()))
    job_repo = _JobRepo()
    runner = RunDailyMatrixDeployJob(
        matrix_sync=_Sync(_state()),
        run_build=build,
        deployer=_Deployer(()),
        job_repository=job_repo,
        snapshot_store=_SnapshotStore(),
        status_repository=_StatusRepo(),
        notifier=_Notifier(),
        clock=_Clock(["2026-07-14T00:00:00Z", "2026-07-14T00:01:00Z"]),
        id_factory=lambda: "job-cron",
        logger=_Logger(),
    )
    runner.run()
    assert job_repo.inserted[0].trigger == "cron"
    assert build.calls == [{"job_id": "job-cron", "seed_only": False}]


def test_daily_job_finalize_has_no_price_stream() -> None:
    """happy: ctor без price_change_stream; finalize → snapshots + notify без stream."""
    params = inspect.signature(RunDailyMatrixDeployJob.__init__).parameters
    assert "price_change_stream" not in params
    payload = MatrixDeployPayload(
        logical_matrix_name="Snacks",
        machine_code="512",
        matrix_multiplier="1.0",
        lines=(
            MatrixDeployPayloadLine(
                line_number=1,
                product_code="A",
                product_name="Cola",
                deploy_price=Decimal("10"),
                capacity=10,
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
    runner, jobs, snapshots, notifier, _deployer, status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=_build(payloads=(payload,)),
        deploy_results=(_result("Snacks", "512", "applied", None),),
    )
    job = runner.run()
    assert job.status == "completed"
    assert snapshots.documents
    assert jobs.finalized == [job]
    assert status.terminal_jobs == [job]
    assert not hasattr(notifier, "price_stream_failed")
