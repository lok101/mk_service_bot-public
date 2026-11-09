from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from src.config._base import ServiceSettingsBase

_HEARTBEAT_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class WorkerLivenessTarget:
    name: str
    status_collection: str


WORKER_LIVENESS_TARGETS_V1: tuple[WorkerLivenessTarget, ...] = (
    WorkerLivenessTarget(
        name="sales-monitoring",
        status_collection="sales_monitoring_worker_status",
    ),
    WorkerLivenessTarget(
        name="matrix",
        status_collection="matrix_worker_status",
    ),
    WorkerLivenessTarget(
        name="daily-sales-demand",
        status_collection="daily_sales_demand_worker_status",
    ),
    WorkerLivenessTarget(
        name="machine-pnl-month",
        status_collection="machine_pnl_month_worker_status",
    ),
    WorkerLivenessTarget(
        name="service-visits",
        status_collection="service_visits_worker_status",
    ),
    WorkerLivenessTarget(
        name="effects-worker",
        status_collection="effects_worker_status",
    ),
)


class WorkerLivenessSettings(ServiceSettingsBase):
    stale_seconds: int = Field(
        default=300,
        validation_alias="WORKER_LIVENESS_STALE_SECONDS",
        gt=_HEARTBEAT_INTERVAL_SECONDS,
    )
    alert_cooldown_seconds: int = Field(
        default=1800,
        validation_alias="WORKER_LIVENESS_ALERT_COOLDOWN_SECONDS",
        ge=1,
    )
    bootstrap_cooldown_seconds: int = Field(
        default=1800,
        validation_alias="WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS",
        ge=1,
    )
