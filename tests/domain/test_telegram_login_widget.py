from __future__ import annotations

import hashlib
import hmac

import pytest

from src.domain.telegram_login_widget import TelegramLoginWidgetError, verify_telegram_login


def _sign(fields: dict[str, str], token: str) -> str:
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k != "hash")
    secret = hashlib.sha256(token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def test_verify_telegram_login_accepts_valid_hash() -> None:
    fields = {"id": "1001", "auth_date": "1700000000", "first_name": "Ops"}
    fields["hash"] = _sign(fields, "bot-token")
    user_id = verify_telegram_login(
        fields,
        bot_token="bot-token",
        max_age_seconds=10**12,
        now_epoch=1700000000,
    )
    assert user_id == 1001


def test_verify_telegram_login_rejects_bad_hash() -> None:
    fields = {"id": "1001", "auth_date": "1700000000", "hash": "00" * 32}
    with pytest.raises(TelegramLoginWidgetError):
        verify_telegram_login(
            fields,
            bot_token="bot-token",
            max_age_seconds=86400,
            now_epoch=1700000000,
        )
