from __future__ import annotations

import pytest

from src.config.bootstrap_alert_env import load_bootstrap_alert_env


def test_load_bootstrap_alert_env_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", " tok ")
    monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", "-1001")
    monkeypatch.setenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", "3600")

    loaded = load_bootstrap_alert_env()

    assert loaded.bot_token == "tok"
    assert loaded.alert_chat_id == -1001
    assert loaded.cooldown_seconds == 3600


def test_load_bootstrap_alert_env_missing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALERT_CHAT_ID", raising=False)
    monkeypatch.delenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", raising=False)

    loaded = load_bootstrap_alert_env()

    assert loaded.bot_token == ""
    assert loaded.alert_chat_id is None
    assert loaded.cooldown_seconds == 1800


@pytest.mark.parametrize(
    ("raw_chat", "raw_cooldown", "expected_chat", "expected_cooldown"),
    [
        ("not-int", None, None, 1800),
        ("-1001", "0", -1001, 1800),
        ("-1001", "bad", -1001, 1800),
        ("-1001", "  ", -1001, 1800),
    ],
)
def test_load_bootstrap_alert_env_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_chat: str,
    raw_cooldown: str | None,
    expected_chat: int | None,
    expected_cooldown: int,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", "bot")
    monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", raw_chat)
    if raw_cooldown is None:
        monkeypatch.delenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", raising=False)
    else:
        monkeypatch.setenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", raw_cooldown)

    loaded = load_bootstrap_alert_env()

    assert loaded.alert_chat_id == expected_chat
    assert loaded.cooldown_seconds == expected_cooldown
