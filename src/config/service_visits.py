from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class ServiceVisitsSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    worker_enabled: bool = Field(
        default=False,
        validation_alias="SERVICE_VISITS_WORKER_ENABLED",
    )
    visits_collection: str = Field(
        default="service_visits",
        validation_alias="MONGODB_SERVICE_VISITS_COLLECTION",
        min_length=1,
    )
    worker_status_collection: str = Field(
        default="service_visits_worker_status",
        validation_alias="MONGODB_SERVICE_VISITS_WORKER_STATUS_COLLECTION",
        min_length=1,
    )
    no_sales_min_baseline_qty: Decimal = Field(
        default=Decimal("0"),
        validation_alias="SERVICE_VISITS_NO_SALES_MIN_BASELINE_QTY",
        ge=0,
    )
    task_notify_enabled: bool = Field(
        default=False,
        validation_alias="SERVICE_VISITS_TASK_NOTIFY_ENABLED",
    )
    task_notify_telegram_chat_id: int | None = Field(
        default=None,
        validation_alias="SERVICE_VISITS_TASK_NOTIFY_TELEGRAM_CHAT_ID",
    )

    @model_validator(mode="after")
    def validate_task_notify_chat_id(self) -> Self:
        if self.task_notify_enabled and self.task_notify_telegram_chat_id is None:
            raise ValueError(
                "SERVICE_VISITS_TASK_NOTIFY_ENABLED=true requires "
                "SERVICE_VISITS_TASK_NOTIFY_TELEGRAM_CHAT_ID",
            )
        return self
