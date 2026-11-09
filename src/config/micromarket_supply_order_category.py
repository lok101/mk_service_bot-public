from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase

_DEFAULT_ATTR_SHELF_LIFE = UUID("c3b612d9-cc7d-11f1-0a80-1d46001735af")
_DEFAULT_FOLDER_SNACKS = UUID("4c2738f1-f43a-11ef-0a80-1a2b002150a4")
_DEFAULT_FOLDER_READY_MEALS = UUID("7203a901-b1b2-11f1-0a80-115a00344501")


class MicromarketSupplyOrderCategorySettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    shelf_life_days_threshold: int = Field(
        default=7,
        validation_alias="MICROMARKET_SUPPLY_SHELF_LIFE_DAYS_THRESHOLD",
        ge=0,
    )
    attr_shelf_life_days_id: UUID = Field(
        default=_DEFAULT_ATTR_SHELF_LIFE,
        validation_alias="MOYSKLAD_ATTR_SHELF_LIFE_DAYS_ID",
    )
    folder_snacks_id: UUID = Field(
        default=_DEFAULT_FOLDER_SNACKS,
        validation_alias="MOYSKLAD_FOLDER_SNACKS_ID",
    )
    folder_ready_meals_id: UUID = Field(
        default=_DEFAULT_FOLDER_READY_MEALS,
        validation_alias="MOYSKLAD_FOLDER_READY_MEALS_ID",
    )
    sync_interval_seconds: int = Field(
        default=300,
        validation_alias="MICROMARKET_SUPPLY_ORDER_CATEGORY_SYNC_INTERVAL_SECONDS",
        ge=60,
    )
    staleness_seconds: int = Field(
        default=600,
        validation_alias="MICROMARKET_SUPPLY_ORDER_CATEGORY_STALENESS_SECONDS",
        ge=60,
    )

    @field_validator(
        "attr_shelf_life_days_id",
        "folder_snacks_id",
        "folder_ready_meals_id",
        mode="before",
    )
    @classmethod
    def _reject_blank_uuid(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must be a non-empty UUID")
        return value

    @model_validator(mode="after")
    def validate_staleness_not_below_interval(self) -> Self:
        if self.staleness_seconds < self.sync_interval_seconds:
            raise ValueError(
                "MICROMARKET_SUPPLY_ORDER_CATEGORY_STALENESS_SECONDS must be >= "
                "MICROMARKET_SUPPLY_ORDER_CATEGORY_SYNC_INTERVAL_SECONDS",
            )
        return self
