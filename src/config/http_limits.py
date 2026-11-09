from __future__ import annotations

from pydantic import Field

from src.config._base import ServiceSettingsBase


class HttpLimitsSettings(ServiceSettingsBase):
    admin_max_body_bytes: int = Field(
        default=1_048_576,
        validation_alias="ADMIN_MAX_BODY_BYTES",
        ge=1,
    )
    telegram_webhook_max_body_bytes: int = Field(
        default=1_048_576,
        validation_alias="TELEGRAM_WEBHOOK_MAX_BODY_BYTES",
        ge=1,
    )
