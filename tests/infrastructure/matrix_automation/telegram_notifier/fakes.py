from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.job_models import (
    MatrixDeployJob,
    MatrixDeployJobUnit,
    ProductSwapBlockedLine,
    StrongPriceIncreaseLine,
)
from src.application.matrix_automation.models import BlockedMatrixEntry, SkuStats

_STARTED = "2026-07-10T00:00:00+00:00"
_FINISHED = "2026-07-10T00:05:00+00:00"
_DELTA = Decimal("30")


def _unit(
    *,
    logical_matrix_name: str = "Snacks",
    machine_code: str = "512",
    deploy_status: str = "applied",
    deploy_reason: str | None = None,
    sku_stats: SkuStats | None = None,
    strong_lines: tuple[StrongPriceIncreaseLine, ...] = (),
    swap_lines: tuple[ProductSwapBlockedLine, ...] = (),
) -> MatrixDeployJobUnit:
    return MatrixDeployJobUnit(
        logical_matrix_name=logical_matrix_name,
        machine_code=machine_code,
        deploy_status=deploy_status,  # type: ignore[arg-type]
        deploy_reason=deploy_reason,
        sku_stats=sku_stats,
        strong_price_increase_lines=strong_lines,
        product_swap_blocked_lines=swap_lines,
    )


def _job(
    *,
    status: str,
    trigger: str = "cron",
    units: tuple[MatrixDeployJobUnit, ...] = (),
    blocked_matrices: tuple[BlockedMatrixEntry, ...] = (),
    auto_sync_disabled_matrices: int = 0,
) -> MatrixDeployJob:
    return MatrixDeployJob.started(
        job_id="job-1",
        started_at=_STARTED,
        trigger=trigger,  # type: ignore[arg-type]
    ).finalize(
        status=status,  # type: ignore[arg-type]
        finished_at=_FINISHED,
        units=units,
        blocked_matrices=blocked_matrices,
        auto_sync_disabled_matrices=auto_sync_disabled_matrices,
    )
