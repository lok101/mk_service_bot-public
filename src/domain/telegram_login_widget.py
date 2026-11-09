from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

from beartype import beartype


class TelegramLoginWidgetError(ValueError):
    """Raised when Telegram Login Widget payload is invalid or stale."""


@beartype
def verify_telegram_login(
    fields: Mapping[str, str],
    *,
    bot_token: str,
    max_age_seconds: int,
    now_epoch: int | None = None,
) -> int:
    if not bot_token:
        raise TelegramLoginWidgetError("Invalid Telegram login")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    provided = fields.get("hash", "")
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if (
        not provided
        or len(provided) != len(expected)
        or not hmac.compare_digest(provided, expected)
    ):
        raise TelegramLoginWidgetError("Invalid Telegram login")
    try:
        user_id = int(fields.get("id", ""))
        auth_date = int(fields.get("auth_date", ""))
    except ValueError as exc:
        raise TelegramLoginWidgetError("Invalid Telegram login") from exc
    if user_id <= 0:
        raise TelegramLoginWidgetError("Invalid Telegram login")
    current = int(time.time()) if now_epoch is None else now_epoch
    if auth_date > current + 60:
        raise TelegramLoginWidgetError("Invalid Telegram login")
    if current - auth_date > max_age_seconds:
        raise TelegramLoginWidgetError("Invalid Telegram login")
    return user_id
