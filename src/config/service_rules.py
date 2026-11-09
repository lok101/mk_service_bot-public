from __future__ import annotations

from typing import Self

from pydantic import AliasChoices, Field, field_validator, model_validator

from src.config._base import ServiceSettingsBase
from src.domain.telegram_limits import TELEGRAM_MEDIA_GROUP_LIMIT


class ServiceRulesSettings(ServiceSettingsBase):
    revision_interval_min_days: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "REVISION_INTERVAL_MIN_DAYS",
            "REVISION_INTERVAL_DAYS",
            "revision_interval_min_days",
        ),
    )
    revision_interval_max_days: int = Field(
        default=12,
        validation_alias=AliasChoices(
            "REVISION_INTERVAL_MAX_DAYS",
            "REVISION_INTERVAL_DAYS",
            "revision_interval_max_days",
        ),
    )

    loading_photos_min_count: int = Field(
        default=2,
        validation_alias=AliasChoices(
            "LOADING_PHOTOS_MIN_COUNT",
            "loading_photos_min_count",
        ),
    )
    loading_photos_max_count: int = Field(
        default=TELEGRAM_MEDIA_GROUP_LIMIT,
        validation_alias=AliasChoices(
            "LOADING_PHOTOS_MAX_COUNT",
            "loading_photos_max_count",
        ),
    )
    maintenance_cooldown_minutes: int = Field(
        default=20,
        validation_alias=AliasChoices(
            "MAINTENANCE_COOLDOWN_MINUTES",
            "maintenance_cooldown_minutes",
        ),
    )

    @field_validator("revision_interval_min_days")
    @classmethod
    def validate_revision_interval_min_days(cls, value: int) -> int:
        if value < 1:
            raise ValueError("REVISION_INTERVAL_MIN_DAYS must be greater than or equal to 1")
        return value

    @field_validator("revision_interval_max_days")
    @classmethod
    def validate_revision_interval_max_days(cls, value: int) -> int:
        if value < 1:
            raise ValueError("REVISION_INTERVAL_MAX_DAYS must be greater than or equal to 1")
        return value

    @field_validator("loading_photos_min_count")
    @classmethod
    def validate_loading_photos_min_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("LOADING_PHOTOS_MIN_COUNT must be greater than or equal to 1")
        return value

    @field_validator("loading_photos_max_count")
    @classmethod
    def validate_loading_photos_max_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("LOADING_PHOTOS_MAX_COUNT must be greater than or equal to 1")
        if value > TELEGRAM_MEDIA_GROUP_LIMIT:
            raise ValueError(
                "LOADING_PHOTOS_MAX_COUNT must be less than or equal to "
                f"{TELEGRAM_MEDIA_GROUP_LIMIT}",
            )
        return value

    @field_validator("maintenance_cooldown_minutes")
    @classmethod
    def validate_maintenance_cooldown_minutes(cls, value: int) -> int:
        if value < 0:
            raise ValueError(
                "MAINTENANCE_COOLDOWN_MINUTES must be greater than or equal to 0",
            )
        return value

    @model_validator(mode="after")
    def validate_revision_interval_bounds(self) -> Self:
        if self.revision_interval_max_days < self.revision_interval_min_days:
            raise ValueError(
                "REVISION_INTERVAL_MAX_DAYS must be greater than or equal to "
                "REVISION_INTERVAL_MIN_DAYS",
            )
        if self.loading_photos_max_count < self.loading_photos_min_count:
            raise ValueError(
                "LOADING_PHOTOS_MAX_COUNT must be greater than or equal to "
                "LOADING_PHOTOS_MIN_COUNT",
            )
        return self

    @property
    def responsibility_period_days(self) -> int:
        """Обратная совместимость для кода, ещё не переведённого на min/max."""
        return self.revision_interval_min_days
