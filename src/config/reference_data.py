from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from src.config._base import ServiceSettingsBase


class ReferenceDataSettings(ServiceSettingsBase):
    sync_interval_seconds: int = Field(
        default=300,
        validation_alias="REFERENCE_DATA_SYNC_INTERVAL_SECONDS",
        ge=1,
    )
    staleness_alert_seconds: int = Field(
        default=1800,
        validation_alias="REFERENCE_DATA_STALENESS_ALERT_SECONDS",
        ge=1,
    )

    @model_validator(mode="after")
    def validate_staleness_not_below_interval(self) -> Self:
        if self.staleness_alert_seconds < self.sync_interval_seconds:
            raise ValueError(
                "REFERENCE_DATA_STALENESS_ALERT_SECONDS must be >= "
                "REFERENCE_DATA_SYNC_INTERVAL_SECONDS",
            )
        return self
