from __future__ import annotations

from typing import Self

from pydantic import Field, SecretStr, model_validator

from src.config._base import ServiceSettingsBase


class SettlementAnalysisSettings(ServiceSettingsBase):
    enabled: bool = Field(
        default=False,
        validation_alias="SETTLEMENT_ANALYSIS_ADMIN_ENABLED",
    )
    prefs_collection: str = Field(
        default="settlement_analysis_prefs",
        validation_alias="MONGODB_SETTLEMENT_ANALYSIS_PREFS_COLLECTION",
        min_length=1,
    )
    session_secret: SecretStr | None = Field(
        default=None,
        validation_alias="ADMIN_SESSION_SECRET",
    )
    telegram_bot_username: str = Field(
        default="",
        validation_alias="TELEGRAM_BOT_USERNAME",
    )
    dev_stub_login_enabled: bool = Field(
        default=False,
        validation_alias="ADMIN_DEV_STUB_LOGIN_ENABLED",
    )

    @model_validator(mode="after")
    def validate_enabled_secrets(self) -> Self:
        if not self.enabled:
            return self
        secret = ""
        if self.session_secret is not None:
            secret = self.session_secret.get_secret_value().strip()
        if not secret:
            raise ValueError(
                "ADMIN_SESSION_SECRET must be set when SETTLEMENT_ANALYSIS_ADMIN_ENABLED=true",
            )
        username = self.telegram_bot_username.strip()
        if username.startswith("@"):
            raise ValueError("TELEGRAM_BOT_USERNAME must not start with @")
        if not self.dev_stub_login_enabled and not username:
            raise ValueError(
                "TELEGRAM_BOT_USERNAME must be set when "
                "SETTLEMENT_ANALYSIS_ADMIN_ENABLED=true "
                "and ADMIN_DEV_STUB_LOGIN_ENABLED=false",
            )
        return self
