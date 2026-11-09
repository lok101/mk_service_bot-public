from __future__ import annotations

from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class MachinePnlSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    enabled: bool = Field(
        default=False,
        validation_alias="MACHINE_PNL_ENABLED",
    )
    unit_cost_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_UNIT_COST_SPREADSHEET_ID",
    )
    unit_cost_sheet_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_UNIT_COST_SHEET_ID",
    )
    tax_enabled: bool = Field(
        default=False,
        validation_alias="MACHINE_PNL_TAX_ENABLED",
    )
    tax_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_TAX_SPREADSHEET_ID",
    )
    tax_sheet_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_TAX_SHEET_ID",
    )
    global_opex_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID",
    )
    global_opex_sheet_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_GLOBAL_OPEX_SHEET_ID",
    )
    location_rent_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID",
    )
    location_rent_sheet_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_LOCATION_RENT_SHEET_ID",
    )
    period_pnl_collection: str = Field(
        default="machine_period_pnl",
        validation_alias="MONGODB_MACHINE_PERIOD_PNL_COLLECTION",
    )
    alert_chat_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_ALERT_CHAT_ID",
    )
    rent_pending_retry_hours: int = Field(
        default=24,
        ge=1,
        validation_alias="MACHINE_PNL_RENT_PENDING_RETRY_HOURS",
    )
    rent_pending_max_attempts: int = Field(
        default=7,
        ge=1,
        validation_alias="MACHINE_PNL_RENT_PENDING_MAX_ATTEMPTS",
    )
    rent_accountant_chat_id: int | None = Field(
        default=None,
        validation_alias="MACHINE_PNL_RENT_ACCOUNTANT_CHAT_ID",
    )
    catalog_cache_ttl_seconds: int = Field(
        default=1800,
        validation_alias="MACHINE_PNL_CATALOG_CACHE_TTL_SECONDS",
        ge=60,
    )

    @field_validator(
        "unit_cost_spreadsheet_id",
        "tax_spreadsheet_id",
        "global_opex_spreadsheet_id",
        "location_rent_spreadsheet_id",
        mode="before",
    )
    @classmethod
    def empty_spreadsheet_id_is_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("alert_chat_id", "rent_accountant_chat_id", mode="before")
    @classmethod
    def empty_chat_id_is_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_sheet_targets_when_enabled(self) -> Self:
        if not self.enabled:
            return self
        missing: list[str] = []
        if self.unit_cost_spreadsheet_id is None:
            missing.append("MACHINE_PNL_UNIT_COST_SPREADSHEET_ID")
        if self.unit_cost_sheet_id is None:
            missing.append("MACHINE_PNL_UNIT_COST_SHEET_ID")
        if self.global_opex_spreadsheet_id is None:
            missing.append("MACHINE_PNL_GLOBAL_OPEX_SPREADSHEET_ID")
        if self.global_opex_sheet_id is None:
            missing.append("MACHINE_PNL_GLOBAL_OPEX_SHEET_ID")
        if self.location_rent_spreadsheet_id is None:
            missing.append("MACHINE_PNL_LOCATION_RENT_SPREADSHEET_ID")
        if self.location_rent_sheet_id is None:
            missing.append("MACHINE_PNL_LOCATION_RENT_SHEET_ID")
        if missing:
            raise ValueError(
                "MACHINE_PNL_ENABLED requires non-empty: " + ", ".join(missing),
            )
        return self
