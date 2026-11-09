from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import NoDecode, SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


def _parse_unique_int_list(
    value: Any,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> tuple[int, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, tuple):
        return value
    raw = value.split(",") if isinstance(value, str) else value
    result: list[int] = []
    seen: set[int] = set()
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        number = int(text)
        if min_value is not None and number < min_value:
            raise ValueError(f"value must be >= {min_value}")
        if max_value is not None and number > max_value:
            raise ValueError(f"value must be <= {max_value}")
        if number in seen:
            continue
        seen.add(number)
        result.append(number)
    return tuple(result)


def _parse_hours(value: Any) -> tuple[int, ...]:
    return _parse_unique_int_list(value, min_value=0, max_value=23)


def _parse_lead_days(value: Any) -> tuple[int, ...]:
    return _parse_unique_int_list(value, min_value=0)


HoursList = Annotated[
    tuple[int, ...],
    NoDecode,
    BeforeValidator(_parse_hours),
]

LeadDaysList = Annotated[
    tuple[int, ...],
    NoDecode,
    BeforeValidator(_parse_lead_days),
]


class EventRemindersSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    worker_enabled: bool = Field(
        default=False,
        validation_alias="EVENT_REMINDERS_WORKER_ENABLED",
    )
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias="EVENT_REMINDERS_TELEGRAM_BOT_TOKEN",
    )
    telegram_chat_id: int | None = Field(
        default=None,
        validation_alias="EVENT_REMINDERS_TELEGRAM_CHAT_ID",
    )
    alert_telegram_chat_id: int | None = Field(
        default=None,
        validation_alias="EVENT_REMINDERS_ALERT_TELEGRAM_CHAT_ID",
    )
    alert_telegram_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias="EVENT_REMINDERS_ALERT_TELEGRAM_BOT_TOKEN",
    )
    tz: str = Field(
        default="Asia/Yekaterinburg",
        validation_alias="EVENT_REMINDERS_TZ",
    )
    hours: HoursList = Field(
        default=(),
        validation_alias="EVENT_REMINDERS_HOURS",
    )
    lead_days: LeadDaysList = Field(
        default=(),
        validation_alias="EVENT_REMINDERS_LEAD_DAYS",
    )
    spreadsheet_id: str = Field(
        default="",
        validation_alias="EVENT_REMINDERS_SPREADSHEET_ID",
    )
    sheet_id: int | None = Field(
        default=None,
        ge=0,
        validation_alias="EVENT_REMINDERS_SHEET_ID",
    )

    @field_validator("telegram_bot_token", "alert_telegram_bot_token", mode="before")
    @classmethod
    def empty_secret_is_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value
