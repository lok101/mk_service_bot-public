from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.infrastructure.alerting import worker_liveness_bootstrap as bootstrap


def _set_bootstrap_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bot_token: str | None = "bot-token",
    chat_id: str | None = "-1001",
    cooldown: str | None = "1800",
) -> None:
    if bot_token is None:
        monkeypatch.delenv("BOT_TOKEN", raising=False)
    else:
        monkeypatch.setenv("BOT_TOKEN", bot_token)
    if chat_id is None:
        monkeypatch.delenv("TELEGRAM_ALERT_CHAT_ID", raising=False)
    else:
        monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", chat_id)
    if cooldown is None:
        monkeypatch.delenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", raising=False)
    else:
        monkeypatch.setenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", cooldown)


def test_bootstrap_alert_sends_once_then_cooldown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set_bootstrap_env(monkeypatch, cooldown="3600")
    sends: list[str] = []

    def fake_send(*, bot_token: str, chat_id: int, text: str) -> None:
        del bot_token, chat_id
        sends.append(text)

    monkeypatch.setattr(bootstrap, "send_telegram_message", fake_send)
    monkeypatch.setattr(bootstrap, "_marker_root", lambda: tmp_path)

    error = RuntimeError("settings boom")
    with caplog.at_level(logging.INFO):
        bootstrap.notify_bootstrap_failure(
            entrypoint="run_sales_monitoring_worker",
            error=error,
        )
        bootstrap.notify_bootstrap_failure(
            entrypoint="run_sales_monitoring_worker",
            error=error,
        )

    assert len(sends) == 1
    assert "run_sales_monitoring_worker" in sends[0]
    assert "RuntimeError" in sends[0]
    assert "settings boom" in sends[0]
    assert "bot-token" not in sends[0]
    assert any("worker_liveness_bootstrap_alert" in r.message for r in caplog.records)
    assert any(
        "cooldown" in r.message or getattr(r, "skip_reason", None) == "cooldown"
        for r in caplog.records
    ) or any("cooldown" in r.getMessage() for r in caplog.records)


def test_bootstrap_alert_skips_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set_bootstrap_env(monkeypatch, bot_token=None, chat_id=None)
    sends: list[str] = []

    def fake_send(*, bot_token: str, chat_id: int, text: str) -> None:
        del bot_token, chat_id
        sends.append(text)

    monkeypatch.setattr(bootstrap, "send_telegram_message", fake_send)
    monkeypatch.setattr(bootstrap, "_marker_root", lambda: tmp_path)

    with caplog.at_level(logging.INFO):
        bootstrap.notify_bootstrap_failure(
            entrypoint="run_matrix_worker",
            error=RuntimeError("missing env"),
        )

    assert sends == []
    assert any("alerts_disabled" in r.getMessage() for r in caplog.records)


def test_bootstrap_alert_send_failure_does_not_swallow_original(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _set_bootstrap_env(monkeypatch)

    def boom_send(*, bot_token: str, chat_id: int, text: str) -> None:
        del bot_token, chat_id, text
        raise OSError("telegram down")

    monkeypatch.setattr(bootstrap, "send_telegram_message", boom_send)
    monkeypatch.setattr(bootstrap, "_marker_root", lambda: tmp_path)

    original = RuntimeError("fatal before settings")
    with caplog.at_level(logging.ERROR):
        bootstrap.notify_bootstrap_failure(
            entrypoint="run.py",
            error=original,
        )

    assert any(
        "telegram down" in r.getMessage() or "failed" in r.getMessage() for r in caplog.records
    )


def test_bootstrap_wrapper_invoked_on_settings_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_sales_monitoring_worker

    calls: list[tuple[str, BaseException]] = []

    def fake_notify(*, entrypoint: str, error: BaseException) -> None:
        calls.append((entrypoint, error))

    def boom_settings() -> object:
        raise ValidationError.from_exception_data(
            "Settings",
            [
                {
                    "type": "missing",
                    "loc": ("BOT_TOKEN",),
                    "input": {},
                }
            ],
        )

    monkeypatch.setattr(run_sales_monitoring_worker, "get_settings", boom_settings)
    monkeypatch.setattr(
        run_sales_monitoring_worker,
        "notify_bootstrap_failure",
        fake_notify,
    )
    monkeypatch.setattr(
        run_sales_monitoring_worker,
        "configure_ops_alert_logging",
        lambda settings: (_ for _ in ()).throw(AssertionError("hooks must not run")),
    )

    with pytest.raises(ValidationError):
        asyncio.run(run_sales_monitoring_worker.main())

    assert len(calls) == 1
    assert calls[0][0] == "run_sales_monitoring_worker"
    assert isinstance(calls[0][1], ValidationError)
