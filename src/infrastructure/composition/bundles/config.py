from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class AppConfig:
    bot_token: str
    telegram_webhook_public_host: str
    telegram_webhook_path: str
    telegram_webhook_secret: str | None
    api_host: str
    api_port: int
    api_log_level: str
    webhook_secret: str
    webhook_signature_max_age_seconds: int
    webhook_max_body_bytes: int
    revision_form_token_secret: str
    inventory_form_token_secret: str
    form_token_field_name: str
    form_token_ttl_hours: float
