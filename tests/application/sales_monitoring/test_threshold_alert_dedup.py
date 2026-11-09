from __future__ import annotations

from src.infrastructure.alerting.snack_sale_unresolved_notifier import (
    TelegramSnackSaleUnresolvedAlertNotifier,
)


def test_threshold_alert_fires_on_first_unresolved_count() -> None:
    """happy: first unresolved/mismatch threshold alert is sent."""
    sent: list[str] = []
    notifier = TelegramSnackSaleUnresolvedAlertNotifier(
        bot_token="t",
        chat_id=1,
        _send=sent.append,
    )

    notifier.notify_unresolved_sales(count=14)

    assert len(sent) == 1
    assert "14 unresolved/mismatch" in sent[0]
    assert "threshold alert" in sent[0]


def test_threshold_alert_suppressed_when_count_unchanged() -> None:
    """edge: same key/generation (unchanged count) is not re-sent."""
    sent: list[str] = []
    notifier = TelegramSnackSaleUnresolvedAlertNotifier(
        bot_token="t",
        chat_id=1,
        _send=sent.append,
    )

    notifier.notify_unresolved_sales(count=14)
    notifier.notify_unresolved_sales(count=14)

    assert len(sent) == 1


def test_threshold_alert_allowed_when_mismatch_count_changes() -> None:
    """error: state change (new count) may alert again."""
    sent: list[str] = []
    notifier = TelegramSnackSaleUnresolvedAlertNotifier(
        bot_token="t",
        chat_id=1,
        _send=sent.append,
    )

    notifier.notify_unresolved_sales(count=14)
    notifier.notify_unresolved_sales(count=11)

    assert len(sent) == 2
    assert "14 unresolved/mismatch" in sent[0]
    assert "11 unresolved/mismatch" in sent[1]
