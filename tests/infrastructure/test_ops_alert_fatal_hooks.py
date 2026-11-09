from __future__ import annotations

import logging
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.alerting.setup import configure_ops_alert_logging


def _google_forms_settings() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("webhook"),
        revision_form_token_secret=SecretStr("revision"),
        loading_form_token_secret=SecretStr("loading"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "warehouse-inventory",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _alert_settings(*, environment: str, alert_chat_id: int | None) -> Settings:
    return Settings.model_construct(
        environment=environment,
        telegram=TelegramSettings(
            BOT_TOKEN=SecretStr("token"),
            TELEGRAM_ALERT_CHAT_ID=alert_chat_id,
        ),
        google_forms=_google_forms_settings(),
    )


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_fatal_excepthook_notifies_ops_alert(mock_send: MagicMock) -> None:
    # happy: simulated fatal hook reaches TelegramAlertHandler path
    settings = _alert_settings(environment="dev", alert_chat_id=-1001)
    previous_hook = sys.excepthook
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    ops_logging = configure_ops_alert_logging(settings)
    assert ops_logging is not None
    assert sys.excepthook is not previous_hook

    try:
        try:
            raise RuntimeError("process fatal boom")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None
            assert exc_value is not None
            sys.excepthook(exc_type, exc_value, exc_tb)
    finally:
        ops_logging.stop()
        ops_logging.restore_exception_hooks()
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)

    assert sys.excepthook is previous_hook
    mock_send.assert_called_once()
    sent_text = mock_send.call_args.kwargs["text"]
    assert "Unhandled exception" in sent_text
    assert "RuntimeError: process fatal boom" in sent_text


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_fatal_excepthook_notifies_after_listener_stop(mock_send: MagicMock) -> None:
    # happy/edge: entry finally stops listener before excepthook; sync emit still alerts
    settings = _alert_settings(environment="dev", alert_chat_id=-1001)
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    ops_logging = configure_ops_alert_logging(settings)
    assert ops_logging is not None
    ops_logging.stop()

    try:
        try:
            raise RuntimeError("fatal after stop")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None
            assert exc_value is not None
            sys.excepthook(exc_type, exc_value, exc_tb)
    finally:
        ops_logging.restore_exception_hooks()
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)

    mock_send.assert_called_once()
    assert "RuntimeError: fatal after stop" in mock_send.call_args.kwargs["text"]


def test_configure_ops_alert_logging_disabled_does_not_install_fatal_hooks() -> None:
    # edge: alerts disabled → no hook install / no crash loop
    settings = _alert_settings(environment="dev", alert_chat_id=None)
    previous_sys_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    assert configure_ops_alert_logging(settings) is None
    assert sys.excepthook is previous_sys_hook
    assert threading.excepthook is previous_thread_hook

    try:
        raise ValueError("should not alert")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        assert exc_type is not None
        assert exc_value is not None
        previous_sys_hook(exc_type, exc_value, exc_tb)


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_fatal_excepthook_notifier_failure_does_not_raise(
    mock_send: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # error: notifier failure logged, not re-raised into crash loop
    mock_send.side_effect = OSError("telegram down")
    settings = _alert_settings(environment="dev", alert_chat_id=-1001)
    previous_hook = sys.excepthook
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    ops_logging = configure_ops_alert_logging(settings)
    assert ops_logging is not None

    try:
        try:
            raise RuntimeError("fatal while notifier broken")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None
            assert exc_value is not None
            sys.excepthook(exc_type, exc_value, exc_tb)
    finally:
        ops_logging.stop()
        ops_logging.restore_exception_hooks()
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)

    assert sys.excepthook is previous_hook
    mock_send.assert_called_once()
    err = capsys.readouterr().err
    assert "OSError" in err
    assert "telegram down" in err
