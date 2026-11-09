from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.matrix_automation.deploy_reasons import (
    INVALID_MATRIX_HEADER,
    INVALID_MATRIX_MULTIPLIER,
    PRODUCT_REFERENCE_INVALID,
    UNKNOWN_PRODUCT_NAME,
)
from src.application.matrix_automation.job_models import (
    JobStatus,
    JobTrigger,
    MatrixDeployJob,
    MatrixDeployJobUnit,
    ProductSwapBlockedLine,
    StrongPriceIncreaseLine,
)
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixDeployResult,
    MatrixDeploySkippedUnit,
    MatrixParseState,
    PriceSnapshotDocument,
    SnapshotLineRecord,
)
from src.application.matrix_automation.ports import (
    MatrixDeployer,
    MatrixDeployJobRepository,
    MatrixJobNotifier,
    MatrixPriceSnapshotStore,
    MatrixWorkerStatusRepository,
    RunMatrixDeployBuildPort,
)
from src.application.matrix_automation.run_matrix_deploy_build import PurchaseFetchGlobalAbort
from src.application.matrix_automation.sku_stats import sku_stats_from_lines
from src.application.matrix_automation.sync import SyncGlobalAbort

BLOCKED_MATRIX_REASONS = frozenset(
    {
        UNKNOWN_PRODUCT_NAME,
        INVALID_MATRIX_MULTIPLIER,
        INVALID_MATRIX_HEADER,
        PRODUCT_REFERENCE_INVALID,
    }
)


class DeployResultKeyMismatch(Exception):
    """Deploy results do not match payload keys exactly."""


@runtime_checkable
class UtcClock(Protocol):
    def now_utc_iso(self) -> str: ...


@runtime_checkable
class MatrixSyncPort(Protocol):
    def sync(self) -> MatrixParseState | SyncGlobalAbort: ...


@runtime_checkable
class JobLogger(Protocol):
    def exception(self, message: str, *args: object, **kwargs: object) -> None: ...

    def warning(self, message: str, *args: object, **kwargs: object) -> None: ...

    def error(self, message: str, *args: object, **kwargs: object) -> None: ...


def terminal_status_for(results: tuple[MatrixDeployResult, ...]) -> JobStatus:
    if not results:
        return "skipped"
    applied = sum(result.status == "applied" for result in results)
    if applied == len(results):
        return "completed"
    if applied:
        return "partial"
    return "failed"


def _increase_pct(*, baseline: Decimal, deploy_price: Decimal) -> str:
    pct = ((deploy_price - baseline) / baseline) * Decimal("100")
    return format(pct.quantize(Decimal("0.1")), "f")


def _strong_lines_from_lines(
    *,
    machine_code: str,
    lines: tuple[MatrixDeployPayloadLine, ...],
) -> tuple[StrongPriceIncreaseLine, ...]:
    result: list[StrongPriceIncreaseLine] = []
    for line in lines:
        if line.outcome != "applied" or not line.strong_price_increase:
            continue
        if line.baseline_price is None:
            continue
        result.append(
            StrongPriceIncreaseLine(
                machine_code=machine_code,
                line_number=line.line_number,
                product_code=line.product_code,
                baseline=format(line.baseline_price, "f"),
                deploy_price=format(line.deploy_price, "f"),
                increase_pct=_increase_pct(
                    baseline=line.baseline_price,
                    deploy_price=line.deploy_price,
                ),
            )
        )
    return tuple(result)


def _strong_lines_from_payload(
    payload: MatrixDeployPayload,
) -> tuple[StrongPriceIncreaseLine, ...]:
    return _strong_lines_from_lines(machine_code=payload.machine_code, lines=payload.lines)


def _swap_lines_from_lines(
    *,
    machine_code: str,
    lines: tuple[MatrixDeployPayloadLine, ...],
) -> tuple[ProductSwapBlockedLine, ...]:
    return tuple(
        ProductSwapBlockedLine(
            machine_code=machine_code,
            line_number=line.line_number,
            current_product=line.product_code,
            desired_product=line.desired_product,
            reason=line.reason,
        )
        for line in lines
        if line.outcome == "product_swap_blocked"
    )


def _swap_lines_from_payload(
    payload: MatrixDeployPayload,
) -> tuple[ProductSwapBlockedLine, ...]:
    return _swap_lines_from_lines(machine_code=payload.machine_code, lines=payload.lines)


@beartype
def job_unit_from_skipped(unit: MatrixDeploySkippedUnit) -> MatrixDeployJobUnit:
    blocked = unit.deploy_reason in BLOCKED_MATRIX_REASONS
    if blocked:
        return MatrixDeployJobUnit(
            logical_matrix_name=unit.logical_matrix_name,
            machine_code=unit.machine_code,
            deploy_status="skipped",
            deploy_reason=unit.deploy_reason,
            sku_stats=None,
            strong_price_increase_lines=(),
            product_swap_blocked_lines=(),
        )
    if unit.lines:
        return MatrixDeployJobUnit(
            logical_matrix_name=unit.logical_matrix_name,
            machine_code=unit.machine_code,
            deploy_status="skipped",
            deploy_reason=unit.deploy_reason,
            sku_stats=sku_stats_from_lines(unit.lines),
            strong_price_increase_lines=_strong_lines_from_lines(
                machine_code=unit.machine_code,
                lines=unit.lines,
            ),
            product_swap_blocked_lines=_swap_lines_from_lines(
                machine_code=unit.machine_code,
                lines=unit.lines,
            ),
        )
    return MatrixDeployJobUnit(
        logical_matrix_name=unit.logical_matrix_name,
        machine_code=unit.machine_code,
        deploy_status="skipped",
        deploy_reason=unit.deploy_reason,
        sku_stats=unit.sku_stats,
        strong_price_increase_lines=(),
        product_swap_blocked_lines=(),
    )


@beartype
def job_unit_from_payload_result(
    payload: MatrixDeployPayload,
    result: MatrixDeployResult,
) -> MatrixDeployJobUnit:
    return MatrixDeployJobUnit(
        logical_matrix_name=payload.logical_matrix_name,
        machine_code=payload.machine_code,
        deploy_status=result.status,
        deploy_reason=None if result.status == "applied" else result.reason,
        sku_stats=sku_stats_from_lines(payload.lines),
        strong_price_increase_lines=_strong_lines_from_payload(payload),
        product_swap_blocked_lines=_swap_lines_from_payload(payload),
    )


@beartype
def snapshot_from_payload(
    *,
    job_id: str,
    payload: MatrixDeployPayload,
    recorded_at: str,
) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id=job_id,
        machine_code=payload.machine_code,
        logical_matrix_name=payload.logical_matrix_name,
        recorded_at=recorded_at,
        lines=tuple(
            SnapshotLineRecord(
                line_number=line.line_number,
                product_code=line.product_code,
                product_name=line.product_name,
                capacity=line.capacity,
                purchase_price=(
                    format(line.purchase_price, "f") if line.purchase_price is not None else None
                ),
                calculated_price=(
                    format(line.calculated_price, "f")
                    if line.calculated_price is not None
                    else None
                ),
                deploy_price=format(line.deploy_price, "f"),
                outcome=line.outcome,
                reason=line.reason,
                strong_price_increase=line.strong_price_increase,
            )
            for line in payload.lines
        ),
    )


@beartype
@dataclass(slots=True)
class RunDailyMatrixDeployJob:
    matrix_sync: MatrixSyncPort
    run_build: RunMatrixDeployBuildPort
    deployer: MatrixDeployer
    job_repository: MatrixDeployJobRepository
    snapshot_store: MatrixPriceSnapshotStore
    status_repository: MatrixWorkerStatusRepository
    notifier: MatrixJobNotifier
    clock: UtcClock
    id_factory: Callable[[], str]
    logger: JobLogger
    seed_only: bool = False
    trigger: JobTrigger = "cron"

    @beartype
    def run(self) -> MatrixDeployJob:
        started_at = self.clock.now_utc_iso()
        job = MatrixDeployJob.started(
            job_id=self.id_factory(),
            started_at=started_at,
            trigger=self.trigger,
        )
        self.job_repository.insert(job)

        sync_result = self.matrix_sync.sync()
        if isinstance(sync_result, SyncGlobalAbort):
            return self._finalize_global_abort(job, reason=sync_result.reason)

        build_result = self.run_build(
            sync_result,
            job_id=job.job_id,
            seed_only=self.seed_only,
        )
        if isinstance(build_result, PurchaseFetchGlobalAbort):
            return self._finalize_global_abort(job, reason=build_result.reason)

        if build_result.payloads:
            results = tuple(self.deployer.deploy(list(build_result.payloads)))
        else:
            results = ()
        try:
            matched = self._match_payloads(build_result, results)
        except DeployResultKeyMismatch:
            return self._finalize_global_abort(
                job,
                reason="deploy_result_key_mismatch",
            )
        units = self._merge_units(build_result, matched)
        return self._finalize_and_notify(job, sync_result, units, matched)

    def _match_payloads(
        self,
        build_result: BuildMatrixDeployResult,
        results: tuple[MatrixDeployResult, ...],
    ) -> tuple[tuple[MatrixDeployPayload, MatrixDeployResult], ...]:
        payload_by_key = {
            (payload.logical_matrix_name, payload.machine_code): payload
            for payload in build_result.payloads
        }
        result_by_key = {
            (result.logical_matrix_name, result.machine_code): result for result in results
        }
        if (
            len(payload_by_key) != len(build_result.payloads)
            or len(result_by_key) != len(results)
            or set(payload_by_key) != set(result_by_key)
        ):
            raise DeployResultKeyMismatch(
                "deploy results must match payload keys exactly "
                f"(payloads={sorted(payload_by_key)}, results={sorted(result_by_key)})"
            )
        return tuple((payload_by_key[key], result_by_key[key]) for key in payload_by_key)

    def _merge_units(
        self,
        build_result: BuildMatrixDeployResult,
        matched: tuple[tuple[MatrixDeployPayload, MatrixDeployResult], ...],
    ) -> tuple[MatrixDeployJobUnit, ...]:
        skipped = tuple(job_unit_from_skipped(unit) for unit in build_result.skipped_units)
        deployed = tuple(
            job_unit_from_payload_result(payload, result) for payload, result in matched
        )
        return skipped + deployed

    def _finalize_and_notify(
        self,
        job: MatrixDeployJob,
        state: MatrixParseState,
        units: tuple[MatrixDeployJobUnit, ...],
        matched: tuple[tuple[MatrixDeployPayload, MatrixDeployResult], ...],
    ) -> MatrixDeployJob:
        finished_at = self.clock.now_utc_iso()
        for payload, result in matched:
            if result.status == "applied":
                self.snapshot_store.save(
                    snapshot_from_payload(
                        job_id=job.job_id,
                        payload=payload,
                        recorded_at=finished_at,
                    )
                )
        deploy_results = tuple(result for _, result in matched)
        finalized = job.finalize(
            status=terminal_status_for(deploy_results),
            finished_at=finished_at,
            units=units,
            blocked_matrices=state.blocked_matrices,
            auto_sync_disabled_matrices=state.auto_sync_disabled_matrices,
        )
        self.job_repository.finalize(finalized)
        self.status_repository.record_terminal_job(finalized)
        self._notify_best_effort(finalized)
        return finalized

    def _finalize_global_abort(self, job: MatrixDeployJob, *, reason: str) -> MatrixDeployJob:
        finished_at = self.clock.now_utc_iso()
        finalized = job.finalize(
            status="failed",
            finished_at=finished_at,
            units=(),
            blocked_matrices=(),
            auto_sync_disabled_matrices=0,
        )
        self.job_repository.finalize(finalized)
        self.status_repository.record_terminal_job(finalized)
        self._notify_best_effort(finalized, reason=reason)
        return finalized

    def _notify_best_effort(
        self,
        job: MatrixDeployJob,
        reason: str | None = None,
    ) -> None:
        try:
            self.notifier.notify(
                job,
                global_abort_reason=reason,
            )
        except Exception:
            self.logger.exception(
                "matrix_deploy_job_telegram_failed",
                extra={"job_id": job.job_id},
            )
