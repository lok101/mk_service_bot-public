from __future__ import annotations

from zoneinfo import ZoneInfo

from beartype import beartype
from pydantic import AliasChoices, Field, field_validator

from src.config._base import ServiceSettingsBase


class ServiceCalendarSettings(ServiceSettingsBase):
    display_timezone: str = Field(
        default="Europe/Moscow",
        validation_alias=AliasChoices(
            "SERVICE_DISPLAY_TIMEZONE",
            "display_timezone",
        ),
    )
    service_day_end_hour: int = Field(
        default=6,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "SERVICE_DAY_END_HOUR",
            "service_day_end_hour",
        ),
    )

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("SERVICE_DISPLAY_TIMEZONE must not be empty")
        try:
            ZoneInfo(normalized)
        except Exception as error:
            raise ValueError(
                f"SERVICE_DISPLAY_TIMEZONE is not a valid IANA timezone: {normalized!r}",
            ) from error
        return normalized

    @beartype
    def zone_info(self) -> ZoneInfo:
        return ZoneInfo(self.display_timezone)
