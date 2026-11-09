from __future__ import annotations

import os
from dataclasses import dataclass

from beartype import beartype

_DEFAULT_COOLDOWN_SECONDS = 1800


@dataclass(frozen=True, slots=True)
class BootstrapAlertEnv:
    """Process-env snapshot for pre-Settings bootstrap ops-alert."""

    bot_token: str
    alert_chat_id: int | None
    cooldown_seconds: int


@beartype
def _parse_cooldown(raw: str | None) -> int:
    if raw is None or not raw.strip():
        return _DEFAULT_COOLDOWN_SECONDS
    try:
        value = int(raw.strip())
    except ValueError:
        return _DEFAULT_COOLDOWN_SECONDS
    if value < 1:
        return _DEFAULT_COOLDOWN_SECONDS
    return value


@beartype
def _parse_chat_id(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


@beartype
def load_bootstrap_alert_env() -> BootstrapAlertEnv:
    """Read bootstrap alert env from the process environment (no dotenv)."""
    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    chat_raw = (os.getenv("TELEGRAM_ALERT_CHAT_ID") or "").strip()
    cooldown_raw = os.getenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS")
    return BootstrapAlertEnv(
        bot_token=bot_token,
        alert_chat_id=_parse_chat_id(chat_raw or None),
        cooldown_seconds=_parse_cooldown(cooldown_raw),
    )


__all__ = ["BootstrapAlertEnv", "load_bootstrap_alert_env"]
