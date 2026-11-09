from __future__ import annotations

from typing import Self

from pydantic import Field, SecretStr, model_validator

from src.config._base import ServiceSettingsBase


class LocationRosterSettings(ServiceSettingsBase):
    enabled: bool = Field(default=False, validation_alias="LOCATION_ROSTER_ENABLED")
    session_secret: SecretStr | None = Field(
        default=None,
        validation_alias="ADMIN_SESSION_SECRET",
    )
    telegram_bot_username: str = Field(
        default="",
        validation_alias="TELEGRAM_BOT_USERNAME",
    )
    session_ttl_seconds: int = Field(
        default=86400,
        validation_alias="ADMIN_SESSION_TTL_SECONDS",
        ge=60,
    )
    telegram_auth_max_age_seconds: int = Field(
        default=86400,
        validation_alias="ADMIN_TELEGRAM_AUTH_MAX_AGE_SECONDS",
        ge=60,
    )
    dev_stub_login_enabled: bool = Field(
        default=False,
        validation_alias="ADMIN_DEV_STUB_LOGIN_ENABLED",
    )
    roster_collection: str = Field(
        default="location_roster",
        validation_alias="MONGODB_LOCATION_ROSTER_COLLECTION",
        min_length=1,
    )
    draft_collection: str = Field(
        default="location_roster_draft",
        validation_alias="MONGODB_LOCATION_ROSTER_DRAFT_COLLECTION",
        min_length=1,
    )
    audit_collection: str = Field(
        default="location_roster_audit",
        validation_alias="MONGODB_LOCATION_ROSTER_AUDIT_COLLECTION",
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_enabled_secrets(self) -> Self:
        if not self.enabled:
            return self
        secret = ""
        if self.session_secret is not None:
            secret = self.session_secret.get_secret_value().strip()
        if not secret:
            raise ValueError("ADMIN_SESSION_SECRET must be set when LOCATION_ROSTER_ENABLED=true")
        username = self.telegram_bot_username.strip()
        if username.startswith("@"):
            raise ValueError("TELEGRAM_BOT_USERNAME must not start with @")
        if not self.dev_stub_login_enabled and not username:
            raise ValueError(
                "TELEGRAM_BOT_USERNAME must be set when LOCATION_ROSTER_ENABLED=true "
                "and ADMIN_DEV_STUB_LOGIN_ENABLED=false",
            )
        return self
