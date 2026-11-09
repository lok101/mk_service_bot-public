from __future__ import annotations

import logging

import pytest

from src.infrastructure.alerting.snack_loading_fail_after_move_notifier import (
    TelegramSnackLoadingFailAfterMoveNotifier,
)


def test_fail_after_move_notifier_calls_send() -> None:
    sent: list[str] = []
    n = TelegramSnackLoadingFailAfterMoveNotifier(
        bot_token="t",
        chat_id=1,
        _send=sent.append,
    )
    n.notify_fail_after_move(machine_code="M1", move_id="mv", run_id="r1")
    assert len(sent) == 1
    assert "M1" in sent[0] and "mv" in sent[0] and "r1" in sent[0]


def test_fail_after_move_notifier_swallows_send_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(_: str) -> None:
        raise RuntimeError("telegram down")

    n = TelegramSnackLoadingFailAfterMoveNotifier(
        bot_token="t",
        chat_id=1,
        _send=_boom,
    )
    with caplog.at_level(logging.ERROR):
        n.notify_fail_after_move(machine_code="M1", move_id="mv", run_id="r1")
    assert any("snack_loading_fail_after_move_alert_failed" in r.message for r in caplog.records)
