from __future__ import annotations

from beartype import beartype
from pydantic import Field, SecretStr

from src.config._base import ServiceSettingsBase


class TelegramSettings(ServiceSettingsBase):
    bot_token: SecretStr = Field(validation_alias="BOT_TOKEN")
    webhook_public_host: str = Field(
        default="",
        validation_alias="TELEGRAM_WEBHOOK_IP",
    )
    webhook_path: str = Field(
        default="/webhooks/telegram",
        validation_alias="TELEGRAM_WEBHOOK_PATH",
    )
    webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias="TELEGRAM_WEBHOOK_SECRET",
    )
    alert_chat_id: int | None = Field(
        default=None,
        validation_alias="TELEGRAM_ALERT_CHAT_ID",
    )
    loading_photos_chat_id: int | None = Field(
        default=None,
        validation_alias="LOADING_PHOTOS_CHAT_ID",
    )
    micromarket_loading_photos_chat_id: int | None = Field(
        default=None,
        validation_alias="MICROMARKET_LOADING_PHOTOS_CHAT_ID",
    )
    photo_integrity_enabled: bool = Field(
        default=True,
        validation_alias="PHOTO_INTEGRITY_ENABLED",
    )
    photo_integrity_alert_chat_id: int | None = Field(
        default=None,
        validation_alias="PHOTO_INTEGRITY_ALERT_CHAT_ID",
    )
    alert_min_interval_seconds: float = Field(
        default=300.0,
        validation_alias="TELEGRAM_ALERT_MIN_INTERVAL_SECONDS",
        gt=0,
    )

    @property
    def alerts_enabled(self) -> bool:
        return self.alert_chat_id is not None

    @property
    def loading_photos_proxy_enabled(self) -> bool:
        return (
            self.loading_photos_chat_id is not None
            or self.micromarket_loading_photos_chat_id is not None
        )

    @property
    def photo_integrity_alerts_enabled(self) -> bool:
        return self.photo_integrity_alert_chat_id is not None

    @property
    def uses_webhook(self) -> bool:
        return bool(self.webhook_public_host.strip())

    @beartype
    def build_webhook_url(self) -> str:
        host = self.webhook_public_host.strip()
        if not host:
            raise ValueError("webhook_public_host must be set to build webhook URL")
        path = self.webhook_path.strip() or "/webhooks/telegram"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"https://{host}{path}"

    @beartype
    def webhook_secret_value(self) -> str | None:
        if self.webhook_secret is None:
            return None
        value = self.webhook_secret.get_secret_value().strip()
        return value or None
