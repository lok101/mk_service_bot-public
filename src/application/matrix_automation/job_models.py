from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from beartype import beartype

from src.application.matrix_automation.models import BlockedMatrixEntry, SkuStats

JobStatus = Literal["completed", "partial", "failed", "skipped"]
UnitStatus = Literal["applied", "failed", "skipped"]
JobTrigger = Literal["seed", "cron", "admin_apply"]


@dataclass(frozen=True, slots=True)
class StrongPriceIncreaseLine:
    machine_code: str
    line_number: int
    product_code: str | None
    baseline: str
    deploy_price: str
    increase_pct: str


@dataclass(frozen=True, slots=True)
class ProductSwapBlockedLine:
    machine_code: str
    line_number: int
    current_product: str | None
    desired_product: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class MatrixDeployJobUnit:
    logical_matrix_name: str
    machine_code: str
    deploy_status: UnitStatus
    deploy_reason: str | None
    sku_stats: SkuStats | None
    strong_price_increase_lines: tuple[StrongPriceIncreaseLine, ...]
    product_swap_blocked_lines: tuple[ProductSwapBlockedLine, ...]


@dataclass(frozen=True, slots=True)
class MatrixDeployJob:
    job_id: str
    started_at: str
    finished_at: str | None
    status: JobStatus | None
    units: tuple[MatrixDeployJobUnit, ...]
    blocked_matrices: tuple[BlockedMatrixEntry, ...]
    auto_sync_disabled_matrices: int
    trigger: JobTrigger

    @classmethod
    @beartype
    def started(
        cls,
        *,
        job_id: str,
        started_at: str,
        trigger: JobTrigger = "cron",
    ) -> MatrixDeployJob:
        return cls(
            job_id=job_id,
            started_at=started_at,
            finished_at=None,
            status=None,
            units=(),
            blocked_matrices=(),
            auto_sync_disabled_matrices=0,
            trigger=trigger,
        )

    @beartype
    def finalize(
        self,
        *,
        status: JobStatus,
        finished_at: str,
        units: tuple[MatrixDeployJobUnit, ...],
        blocked_matrices: tuple[BlockedMatrixEntry, ...],
        auto_sync_disabled_matrices: int,
    ) -> MatrixDeployJob:
        if not finished_at:
            raise ValueError("finished_at is required for terminal job")
        return replace(
            self,
            status=status,
            finished_at=finished_at,
            units=units,
            blocked_matrices=blocked_matrices,
            auto_sync_disabled_matrices=auto_sync_disabled_matrices,
        )
