from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.matrix_automation.daily_job import (
    DeployResultKeyMismatch,
    job_unit_from_payload_result,
    snapshot_from_payload,
    terminal_status_for,
)
from src.application.matrix_automation.job_models import JobTrigger, MatrixDeployJob
from src.application.matrix_automation.layout_parse import enabled_matrix_from_layout
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    MatrixDeployPayload,
    MatrixDeployResult,
    MatrixParseState,
)
from src.application.matrix_automation.planogram_product_code import (
    kit_product_code,
    skipped_product_name,
)
from src.application.matrix_automation.ports import (
    MatrixBaseMarginStore,
    MatrixDeployer,
    MatrixDeployJobRepository,
    MatrixPriceSnapshotStore,
    RunMatrixDeployBuildPort,
    SnackMachineLayoutStore,
)
from src.application.matrix_automation.run_matrix_deploy_build import PurchaseFetchGlobalAbort
from src.application.matrix_automation.snack_machine_layout import SnackMachineLayoutCell
from src.application.product_identity.ports import DomainProductStore


class ApplySnackMatrixRejected(Exception):
    @beartype
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@beartype
@dataclass(frozen=True, slots=True)
class ApplySnackMatrixResult:
    skipped_names: tuple[str, ...] = ()


@runtime_checkable
class UtcClock(Protocol):
    def now_utc_iso(self) -> str: ...


@beartype
@dataclass(slots=True)
class ApplySnackMatrix:
    layouts: SnackMachineLayoutStore
    base_margin_store: MatrixBaseMarginStore
    snapshots: MatrixPriceSnapshotStore
    deployer: MatrixDeployer
    run_build: RunMatrixDeployBuildPort
    job_repository: MatrixDeployJobRepository
    clock: UtcClock
    id_factory: Callable[[], str]
    products: DomainProductStore | None = None

    @beartype
    def execute(self, *, machine_code: str, actor_telegram_user_id: int) -> ApplySnackMatrixResult:
        del actor_telegram_user_id
        if self.base_margin_store.get() is None:
            raise ApplySnackMatrixRejected(
                "base margin is not loaded",
                code="base_margin_not_loaded",
            )
        layout = self.layouts.get(machine_code)
        if layout is None:
            raise ApplySnackMatrixRejected(
                f"layout not found for machine {machine_code}",
                code="layout_not_found",
            )

        skipped_names: tuple[str, ...] = ()
        deploy_layout = layout
        if self.products is not None:
            publishable: list[SnackMachineLayoutCell] = []
            skipped: list[str] = []
            for cell in layout.cells:
                code = kit_product_code(cell, self.products)
                name = skipped_product_name(cell, self.products)
                if name is not None:
                    skipped.append(name)
                if code is None:
                    continue
                publishable.append(replace(cell, product_code=code, domain_product_id=None))
            skipped_names = tuple(skipped)
            if not publishable:
                raise ApplySnackMatrixRejected(
                    "nothing to send to Kit",
                    code="nothing_to_send",
                )
            deploy_layout = replace(layout, cells=tuple(publishable))

        state = MatrixParseState(
            enabled_matrices=(enabled_matrix_from_layout(deploy_layout),),
            blocked_matrices=(),
            product_block_map={},
            auto_sync_disabled_matrices=0,
        )
        started_at = self.clock.now_utc_iso()
        job = MatrixDeployJob.started(
            job_id=self.id_factory(),
            started_at=started_at,
            trigger=_ADMIN_APPLY_TRIGGER,
        )
        self.job_repository.insert(job)
        build_result = self.run_build(state, job_id=job.job_id, seed_only=False)
        if isinstance(build_result, PurchaseFetchGlobalAbort):
            self._finalize_failed(job, finished_at=self.clock.now_utc_iso())
            raise ApplySnackMatrixRejected(
                build_result.reason,
                code=build_result.reason,
            )
        if not build_result.payloads:
            self._finalize_failed(job, finished_at=self.clock.now_utc_iso())
            raise ApplySnackMatrixRejected(
                "no deploy payloads produced",
                code="deploy_failed",
            )
        results = tuple(self.deployer.deploy(list(build_result.payloads)))
        try:
            matched = _match_payloads(build_result, results)
        except DeployResultKeyMismatch:
            self._finalize_failed(job, finished_at=self.clock.now_utc_iso())
            raise ApplySnackMatrixRejected(
                "deploy result key mismatch",
                code="deploy_failed",
            ) from None
        finished_at = self.clock.now_utc_iso()
        applied_any = False
        units = []
        for payload, result in matched:
            units.append(job_unit_from_payload_result(payload, result))
            if result.status == "applied":
                applied_any = True
                self.snapshots.save(
                    snapshot_from_payload(
                        job_id=job.job_id,
                        payload=payload,
                        recorded_at=finished_at,
                    )
                )
        if not applied_any:
            self.job_repository.finalize(
                job.finalize(
                    status=terminal_status_for(tuple(result for _, result in matched)),
                    finished_at=finished_at,
                    units=tuple(units),
                    blocked_matrices=state.blocked_matrices,
                    auto_sync_disabled_matrices=state.auto_sync_disabled_matrices,
                )
            )
            raise ApplySnackMatrixRejected(
                "kit deploy failed",
                code="deploy_failed",
            )
        self.job_repository.finalize(
            job.finalize(
                status=terminal_status_for(tuple(result for _, result in matched)),
                finished_at=finished_at,
                units=tuple(units),
                blocked_matrices=state.blocked_matrices,
                auto_sync_disabled_matrices=state.auto_sync_disabled_matrices,
            )
        )
        return ApplySnackMatrixResult(skipped_names=skipped_names)

    @beartype
    def _finalize_failed(self, job: MatrixDeployJob, *, finished_at: str) -> None:
        self.job_repository.finalize(
            job.finalize(
                status="failed",
                finished_at=finished_at,
                units=(),
                blocked_matrices=(),
                auto_sync_disabled_matrices=0,
            )
        )


_ADMIN_APPLY_TRIGGER: JobTrigger = "admin_apply"


@beartype
def _match_payloads(
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
