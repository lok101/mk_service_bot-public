from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class SettlementSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    sales_coverage_tolerance_seconds: int = Field(
        default=0,
        validation_alias="SETTLEMENT_SALES_COVERAGE_TOLERANCE_SECONDS",
        ge=0,
    )
    audit_timezone: ZoneInfo = Field(
        default=ZoneInfo("Europe/Moscow"),
        validation_alias="SETTLEMENT_AUDIT_TIMEZONE",
    )
    auto_reconcile_enabled: bool = Field(
        default=False,
        validation_alias="SETTLEMENT_AUTO_RECONCILE_ENABLED",
    )
    portion_reconcile_quarantine_seconds: int = Field(
        default=86400,
        validation_alias="SETTLEMENT_PORTION_RECONCILE_QUARANTINE_SECONDS",
        ge=0,
    )

    @field_validator("audit_timezone", mode="before")
    @classmethod
    def parse_audit_timezone(cls, value: object) -> ZoneInfo:
        if isinstance(value, ZoneInfo):
            return value
        try:
            return ZoneInfo(str(value))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid SETTLEMENT_AUDIT_TIMEZONE") from exc
