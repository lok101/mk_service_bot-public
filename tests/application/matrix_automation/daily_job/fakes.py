from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.application.matrix_automation.daily_job import RunDailyMatrixDeployJob
from src.application.matrix_automation.job_models import MatrixDeployJob
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixDeployPayload,
    MatrixDeployResult,
    MatrixParseState,
    PriceSnapshotDocument,
)


class _Clock:
    def __init__(self, values: list[str]) -> None:
        self._values = list(values)

    def now_utc_iso(self) -> str:
        return self._values.pop(0)


class _JobRepo:
    def __init__(self) -> None:
        self.inserted: list[MatrixDeployJob] = []
        self.finalized: list[MatrixDeployJob] = []

    def insert(self, job: MatrixDeployJob) -> None:
        self.inserted.append(job)

    def finalize(self, job: MatrixDeployJob) -> None:
        self.finalized.append(job)


class _SnapshotStore:
    def __init__(self) -> None:
        self.documents: list[PriceSnapshotDocument] = []

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
        self.documents.append(document)


class _StatusRepo:
    def __init__(self) -> None:
        self.terminal_jobs: list[MatrixDeployJob] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        return None

    def record_terminal_job(self, job: MatrixDeployJob) -> None:
        self.terminal_jobs.append(job)


class _Notifier:
    def __init__(self) -> None:
        self.jobs: list[MatrixDeployJob] = []
        self.abort_reasons: list[str | None] = []

    def notify(
        self,
        job: MatrixDeployJob,
        *,
        global_abort_reason: str | None = None,
    ) -> None:
        self.jobs.append(job)
        self.abort_reasons.append(global_abort_reason)


class _Sync:
    def __init__(self, result: MatrixParseState | Any) -> None:
        self._result = result

    def sync(self) -> MatrixParseState | Any:
        return self._result


class _Build:
    def __init__(self, result: BuildMatrixDeployResult | Any) -> None:
        self._result = result

    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult | Any:
        return self._result


class _RecordingBuild:
    def __init__(self, result: BuildMatrixDeployResult) -> None:
        self._result = result
        self.calls: list[tuple[str, MatrixParseState, bool]] = []

    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult:
        self.calls.append((job_id, state, seed_only))
        return self._result


class _Deployer:
    def __init__(self, results: tuple[MatrixDeployResult, ...]) -> None:
        self._results = results
        self.calls: list[list[MatrixDeployPayload]] = []

    def deploy(self, payloads: list[MatrixDeployPayload]) -> list[MatrixDeployResult]:
        self.calls.append(payloads)
        return list(self._results)


class _CrashingSync:
    def sync(self) -> MatrixParseState:
        raise RuntimeError("boom after insert")


class _Logger:
    def __init__(self) -> None:
        self.exceptions: list[str] = []

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self.exceptions.append(message % args if args else message)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        return None

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        return None


def _matrix(name: str, *machine_codes: str) -> EnabledLogicalMatrix:
    return EnabledLogicalMatrix(
        logical_matrix_name=name,
        machine_codes=machine_codes,
        matrix_multiplier=Decimal("1"),
        cells=(MatrixCatalogCell(1, "Cola", "A"),),
    )


def _state(
    *,
    enabled_matrices: tuple[EnabledLogicalMatrix, ...] = (),
    blocked_matrices: tuple[Any, ...] = (),
    auto_sync_disabled_matrices: int = 0,
) -> MatrixParseState:
    return MatrixParseState(
        enabled_matrices=enabled_matrices,
        blocked_matrices=blocked_matrices,
        product_block_map={},
        auto_sync_disabled_matrices=auto_sync_disabled_matrices,
    )


def _payload(name: str, machine_code: str) -> MatrixDeployPayload:
    return MatrixDeployPayload(
        logical_matrix_name=name,
        machine_code=machine_code,
        matrix_multiplier="1.0",
        lines=(),
    )


def _build(
    *,
    payloads: tuple[MatrixDeployPayload, ...] = (),
    skipped_units: tuple[Any, ...] = (),
) -> BuildMatrixDeployResult:
    return BuildMatrixDeployResult(payloads=payloads, skipped_units=skipped_units)


def _result(
    name: str,
    machine_code: str,
    status: str,
    reason: str | None,
) -> MatrixDeployResult:
    return MatrixDeployResult(
        logical_matrix_name=name,
        machine_code=machine_code,
        status=status,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
    )


def _runner(
    *,
    sync_result: MatrixParseState | Any | None = None,
    build_result: BuildMatrixDeployResult | Any | None = None,
    deploy_results: tuple[MatrixDeployResult, ...] = (),
    clock_values: list[str] | None = None,
    matrix_sync: Any | None = None,
    run_build: Any | None = None,
    id_factory: Any | None = None,
) -> tuple[RunDailyMatrixDeployJob, _JobRepo, _SnapshotStore, _Notifier, _Deployer, _StatusRepo]:
    jobs = _JobRepo()
    snapshots = _SnapshotStore()
    notifier = _Notifier()
    status = _StatusRepo()
    deployer = _Deployer(deploy_results)
    runner = RunDailyMatrixDeployJob(
        matrix_sync=matrix_sync if matrix_sync is not None else _Sync(sync_result),
        run_build=run_build if run_build is not None else _Build(build_result),
        deployer=deployer,
        job_repository=jobs,
        snapshot_store=snapshots,
        status_repository=status,
        notifier=notifier,
        clock=_Clock(clock_values or ["2026-07-10T00:00:00+00:00", "2026-07-10T00:01:00+00:00"]),
        id_factory=id_factory if id_factory is not None else (lambda: "job-1"),
        logger=_Logger(),
    )
    return runner, jobs, snapshots, notifier, deployer, status
