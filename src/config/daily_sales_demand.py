from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class DailySalesDemandSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    worker_enabled: bool = Field(
        default=False,
        validation_alias="DAILY_SALES_DEMAND_WORKER_ENABLED",
    )
    cron_hour: int = Field(
        default=4,
        validation_alias="DAILY_SALES_DEMAND_WORKER_CRON_HOUR",
        ge=0,
        le=23,
    )
    not_ready_retry_minutes: int = Field(
        default=15,
        validation_alias="DAILY_SALES_DEMAND_NOT_READY_RETRY_MINUTES",
        ge=1,
    )
    not_ready_max_attempts: int = Field(
        default=48,
        validation_alias="DAILY_SALES_DEMAND_NOT_READY_MAX_ATTEMPTS",
        ge=1,
    )
