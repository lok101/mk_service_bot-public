from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.daily_job import RunDailyMatrixDeployJob
from src.application.matrix_automation.job_models import MatrixDeployJob
from src.application.matrix_automation.models import (
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    PriceSnapshotDocument,
)

from .fakes import (
    _Build,
    _build,
    _Clock,
    _Deployer,
    _JobRepo,
    _Logger,
    _matrix,
    _payload,
    _result,
    _SnapshotStore,
    _state,
    _StatusRepo,
    _Sync,
)


def test_notifier_receives_only_finalized_job_after_repository_finalize() -> None:
    events: list[str] = []

    class _TrackingJobs:
        inserted: list[MatrixDeployJob]
        finalized: list[MatrixDeployJob]

        def __init__(self) -> None:
            self.inserted = []
            self.finalized = []

        def insert(self, job: MatrixDeployJob) -> None:
            events.append("insert")
            self.inserted.append(job)

        def finalize(self, job: MatrixDeployJob) -> None:
            events.append("finalize")
            self.finalized.append(job)

    class _TrackingSnapshots:
        documents: list[PriceSnapshotDocument]

        def __init__(self) -> None:
            self.documents = []

        def has_unit_snapshot(self, *, machine_code: str, logical_matrix_name: str) -> bool:
            return False

        def get_latest_line(
            self,
            *,
            machine_code: str,
            logical_matrix_name: str,
            line_number: int,
        ) -> PriceSnapshotDocument | None:
            return None

        def list_latest_for_machine(
            self,
            *,
            machine_code: str,
        ) -> tuple[PriceSnapshotDocument, ...]:
            return ()

        def save(self, document: PriceSnapshotDocument) -> None:
            events.append("snapshot")
            self.documents.append(document)

    class _TrackingStatus:
        terminal_jobs: list[MatrixDeployJob]

        def __init__(self) -> None:
            self.terminal_jobs = []

        def record_heartbeat(self, *, at: str, enabled: bool) -> None:
            return None

        def record_terminal_job(self, job: MatrixDeployJob) -> None:
            events.append("status")
            self.terminal_jobs.append(job)

    class _TrackingNotifier:
        jobs: list[MatrixDeployJob]

        def __init__(self) -> None:
            self.jobs = []

        def notify(
            self,
            job: MatrixDeployJob,
            *,
            global_abort_reason: str | None = None,
        ) -> None:
            events.append("notify")
            self.jobs.append(job)

    jobs = _TrackingJobs()
    snapshots = _TrackingSnapshots()
    status = _TrackingStatus()
    notifier = _TrackingNotifier()
    stream_payload = MatrixDeployPayload(
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
    runner = RunDailyMatrixDeployJob(
        matrix_sync=_Sync(_state(enabled_matrices=(_matrix("Snacks", "512"),))),
        run_build=_Build(_build(payloads=(stream_payload,))),
        deployer=_Deployer((_result("Snacks", "512", "applied", None),)),
        job_repository=jobs,
        snapshot_store=snapshots,
        status_repository=status,
        notifier=notifier,
        clock=_Clock(["2026-07-10T00:00:00+00:00", "2026-07-10T00:01:00+00:00"]),
        id_factory=lambda: "job-1",
        logger=_Logger(),
    )
    job = runner.run()
    assert events == ["insert", "snapshot", "finalize", "status", "notify"]
    assert notifier.jobs == [job]
    assert jobs.finalized == [job]


def test_notifier_exception_does_not_change_terminal_job() -> None:
    class _FailingNotifier:
        def notify(
            self,
            job: MatrixDeployJob,
            *,
            global_abort_reason: str | None = None,
        ) -> None:
            raise OSError("telegram down")

    jobs = _JobRepo()
    status = _StatusRepo()
    runner = RunDailyMatrixDeployJob(
        matrix_sync=_Sync(_state(enabled_matrices=(_matrix("Snacks", "512"),))),
        run_build=_Build(_build(payloads=(_payload("Snacks", "512"),))),
        deployer=_Deployer((_result("Snacks", "512", "applied", None),)),
        job_repository=jobs,
        snapshot_store=_SnapshotStore(),
        status_repository=status,
        notifier=_FailingNotifier(),
        clock=_Clock(["2026-07-10T00:00:00+00:00", "2026-07-10T00:01:00+00:00"]),
        id_factory=lambda: "job-1",
        logger=_Logger(),
    )
    job = runner.run()
    assert job.status == "completed"
    assert job.finished_at is not None
    assert jobs.finalized == [job]
    assert status.terminal_jobs == [job]
