from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class MachinePnlMonthSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    enabled: bool = Field(
        default=False,
        validation_alias="MACHINE_PNL_MONTH_ENABLED",
    )
    ratio_lookback_periods: int = Field(
        default=3,
        ge=1,
        validation_alias="MACHINE_PNL_MONTH_RATIO_LOOKBACK_PERIODS",
    )
    worker_enabled: bool = Field(
        default=False,
        validation_alias="MACHINE_PNL_MONTH_WORKER_ENABLED",
    )
    worker_interval_hours: int = Field(
        default=24,
        ge=1,
        validation_alias="MACHINE_PNL_MONTH_WORKER_INTERVAL_HOURS",
    )
    sheet_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_MONTH_SHEET_SPREADSHEET_ID",
    )
    sheet_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_MONTH_SHEET_ID",
    )
    snapshot_collection: str = Field(
        default="machine_pnl_month_snapshot",
        validation_alias="MONGODB_MACHINE_PNL_MONTH_SNAPSHOT_COLLECTION",
    )

    @field_validator("sheet_spreadsheet_id", mode="before")
    @classmethod
    def empty_spreadsheet_id_is_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value
