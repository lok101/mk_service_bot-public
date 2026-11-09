from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.config.telegram import TelegramSettings


def test_uses_webhook_when_public_host_set() -> None:
    settings = TelegramSettings(
        BOT_TOKEN=SecretStr("token"),
        TELEGRAM_WEBHOOK_IP="203.0.113.10",
    )
    assert settings.uses_webhook is True
    assert settings.build_webhook_url() == "https://203.0.113.10/webhooks/telegram"


def test_uses_polling_when_public_host_empty() -> None:
    settings = TelegramSettings(
        BOT_TOKEN=SecretStr("token"),
        TELEGRAM_WEBHOOK_IP="",
    )
    assert settings.uses_webhook is False


def test_build_webhook_url_custom_path() -> None:
    settings = TelegramSettings(
        BOT_TOKEN=SecretStr("token"),
        TELEGRAM_WEBHOOK_IP="bot.example.com",
        TELEGRAM_WEBHOOK_PATH="/tg-hook",
    )
    assert settings.build_webhook_url() == "https://bot.example.com/tg-hook"


def test_build_webhook_url_requires_host() -> None:
    settings = TelegramSettings(BOT_TOKEN=SecretStr("token"))
    with pytest.raises(ValueError, match="webhook_public_host"):
        settings.build_webhook_url()


def test_alert_min_interval_must_be_positive() -> None:
    with pytest.raises(ValueError):
        TelegramSettings(
            BOT_TOKEN=SecretStr("token"),
            TELEGRAM_ALERT_MIN_INTERVAL_SECONDS=0,
        )
