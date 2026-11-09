from __future__ import annotations

import json
import logging
import logging.config
import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from uvicorn.config import LOGGING_CONFIG

from src.config.event_reminders import EventRemindersSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.micromarket_loading import MicromarketLoadingSettings
from src.config.object_storage import ObjectStorageSettings
from src.config.sales_monitoring import SalesMonitoringSettings
from src.config.settings import Settings
from src.config.snack_loading import SnackLoadingSettings
from src.config.telegram import TelegramSettings
from src.infrastructure.alerting.setup import collect_redaction_secrets, configure_ops_alert_logging
from src.infrastructure.alerting.telegram_log_handler import (
    TelegramAlertHandler,
    format_alert_message,
    redact_secrets,
    send_telegram_message,
)


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


def test_collect_redaction_secrets_includes_warehouse_snack_and_s3() -> None:
    settings = _alert_settings(environment="prod", alert_chat_id=-1001)
    settings = settings.model_copy(
        update={
            "object_storage": ObjectStorageSettings.model_construct(
                s3_secret_access_key=SecretStr("s3-secret-value-16"),
            ),
            "snack_loading": SnackLoadingSettings.model_construct(
                inventory_form_now_token_secret=SecretStr("snack-now-secret-xx"),
            ),
            "master_data": settings.master_data.model_copy(
                update={"session_secret": SecretStr("admin-session-secret")},
            ),
            "sales_monitoring": SalesMonitoringSettings.model_construct(
                telegram_bot_token=SecretStr("sales-bot-token-xx"),
                alert_telegram_bot_token=SecretStr("sales-alert-token-xx"),
            ),
            "event_reminders": EventRemindersSettings.model_construct(
                telegram_bot_token=SecretStr("reminders-bot-token-x"),
                alert_telegram_bot_token=SecretStr("reminders-alert-token-x"),
            ),
        },
    )
    secrets = collect_redaction_secrets(settings)
    assert "warehouse-inventory" in secrets
    assert "s3-secret-value-16" in secrets
    assert "snack-now-secret-xx" in secrets
    assert "admin-session-secret" in secrets
    assert "sales-bot-token-xx" in secrets
    assert "sales-alert-token-xx" in secrets
    assert "reminders-bot-token-x" in secrets
    assert "reminders-alert-token-x" in secrets


def test_collect_redaction_secrets_includes_micromarket_form_tokens() -> None:
    # happy
    settings = _alert_settings(environment="prod", alert_chat_id=-1001)
    settings = settings.model_copy(
        update={
            "micromarket_loading": MicromarketLoadingSettings.model_construct(
                inventory_form_now_token_secret=SecretStr("mm-now-secret-xxxx"),
                inventory_form_as_of_token_secret=SecretStr("mm-asof-secret-xxx"),
            ),
        },
    )
    secrets = collect_redaction_secrets(settings)
    assert "mm-now-secret-xxxx" in secrets
    assert "mm-asof-secret-xxx" in secrets


def test_alerts_enabled_when_chat_id_set() -> None:
    settings = TelegramSettings(
        BOT_TOKEN=SecretStr("token"),
        TELEGRAM_ALERT_CHAT_ID=-1001234567890,
    )
    assert settings.alerts_enabled is True


def test_alerts_disabled_when_chat_id_missing() -> None:
    settings = TelegramSettings(BOT_TOKEN=SecretStr("token"))
    assert settings.alerts_enabled is False


def test_format_alert_message_includes_logger_and_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="src.infrastructure.outbox.worker",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Outbox handler failed for entry %s",
            args=("abc-123",),
            exc_info=sys.exc_info(),
        )

    text = format_alert_message(record=record, environment="prod")

    assert "ERROR mk_service_bot [prod]" in text
    assert "logger: src.infrastructure.outbox.worker" in text
    assert "Outbox handler failed for entry abc-123" in text
    assert "ValueError: boom" in text


def test_format_alert_message_with_exc_info_true() -> None:
    try:
        raise RuntimeError("from bool")
    except RuntimeError:
        record = logging.LogRecord(
            name="src.infrastructure.outbox.worker",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Handler crashed",
            args=(),
            exc_info=True,
        )
        text = format_alert_message(record=record, environment="prod")

    assert "RuntimeError: from bool" in text


def test_format_alert_message_truncates_long_text() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="x" * 5000,
        args=(),
        exc_info=None,
    )

    text = format_alert_message(record=record, environment="dev")

    assert len(text) <= 4000
    assert text.endswith("...(truncated)")


def test_format_alert_message_keeps_traceback_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    # edge: root cause в хвосте длинного traceback
    marker = "ROOT_CAUSE_UNIQUE_LINE_ZX9"
    fake_tb = ("head-frame\n" * 400) + marker + "\n"

    def fake_format_exception(*args: object, **kwargs: object) -> list[str]:
        del args, kwargs
        return [fake_tb]

    monkeypatch.setattr(
        "src.infrastructure.alerting.telegram_log_handler.traceback.format_exception",
        fake_format_exception,
    )
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord(
            name="src.foo",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="ops failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    text = format_alert_message(record=record, environment="prod")
    assert "ERROR mk_service_bot [prod]" in text
    assert "logger: src.foo" in text
    assert "ops failed" in text
    assert marker in text
    assert "head-frame" not in text or text.index(marker) > text.index("logger:")
    assert len(text) <= 4000
    assert "...(truncated)" in text


def test_redact_secrets_replaces_known_values() -> None:
    text = "token=super-secret-token and more"
    redacted = redact_secrets(text, ("super-secret-token",))
    assert redacted == "token=*** and more"
    assert "super-secret-token" not in redacted


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_handler_sends_error_record(mock_send: MagicMock) -> None:
    handler = TelegramAlertHandler(
        bot_token="bot-token",
        chat_id=-1001,
        environment="prod",
        min_interval_seconds=300.0,
        redact_values=(),
    )
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Something failed",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["bot_token"] == "bot-token"
    assert kwargs["chat_id"] == -1001
    assert "Something failed" in kwargs["text"]


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_handler_throttles_duplicate_records(mock_send: MagicMock) -> None:
    handler = TelegramAlertHandler(
        bot_token="bot-token",
        chat_id=-1001,
        environment="prod",
        min_interval_seconds=300.0,
        redact_values=(),
    )
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Repeated failure",
        args=(),
        exc_info=None,
    )

    handler.emit(record)
    handler.emit(record)

    mock_send.assert_called_once()


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_handler_redacts_secrets_in_message(mock_send: MagicMock) -> None:
    handler = TelegramAlertHandler(
        bot_token="bot-token",
        chat_id=-1001,
        environment="prod",
        min_interval_seconds=300.0,
        redact_values=("leaked-secret",),
    )
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Auth failed with leaked-secret",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    sent_text = mock_send.call_args.kwargs["text"]
    assert "leaked-secret" not in sent_text
    assert "***" in sent_text


@patch("urllib.request.urlopen")
def test_send_telegram_message_posts_json(mock_urlopen: MagicMock) -> None:
    response = MagicMock()
    response.status = 200
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = response

    send_telegram_message(bot_token="bot-token", chat_id=-1001, text="hello")

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "https://api.telegram.org/botbot-token/sendMessage"
    assert request.data is not None
    assert b'"chat_id": -1001' in request.data
    assert b'"text": "hello"' in request.data


def test_configure_ops_alert_logging_disabled_in_test_env() -> None:
    settings = _alert_settings(environment="test", alert_chat_id=-1001)

    assert configure_ops_alert_logging(settings) is None


def test_configure_ops_alert_logging_disabled_without_chat_id() -> None:
    settings = _alert_settings(environment="dev", alert_chat_id=None)

    assert configure_ops_alert_logging(settings) is None


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_configure_ops_alert_logging_enables_root_queue_handler(mock_send: MagicMock) -> None:
    settings = _alert_settings(environment="dev", alert_chat_id=-1001)
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    ops_logging = configure_ops_alert_logging(settings)
    assert ops_logging is not None

    try:
        added_handlers = [
            handler for handler in root_logger.handlers if handler not in handlers_before
        ]
        assert any(handler.__class__.__name__ == "QueueHandler" for handler in added_handlers)

        logging.getLogger("test.ops.alert").error("integration failure")
    finally:
        ops_logging.stop()
        ops_logging.restore_exception_hooks()
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)

    mock_send.assert_called_once()
    assert "integration failure" in mock_send.call_args.kwargs["text"]


@patch("urllib.request.urlopen")
def test_ops_alert_sends_error_to_configured_admin_chat(mock_urlopen: MagicMock) -> None:
    """End-to-end: ERROR log → queue → handler → Bot API with TELEGRAM_ALERT_CHAT_ID."""
    admin_chat_id = -1001234567890
    bot_token = "test-bot-token"
    settings = Settings.model_construct(
        environment="prod",
        telegram=TelegramSettings(
            BOT_TOKEN=SecretStr(bot_token),
            TELEGRAM_ALERT_CHAT_ID=admin_chat_id,
        ),
        google_forms=GoogleFormsSettings.model_construct(
            webhook_secret=SecretStr("wh-sec-abc"),
            revision_form_token_secret=SecretStr("rev-sec-abc"),
            loading_form_token_secret=SecretStr("load-sec-abc"),
            revision_form_url="https://forms.example/revision",
            loading_form_url="https://forms.example/loading",
            revision_form_token_entry_id="entry.1",
            loading_form_token_entry_id="entry.2",
            technician_warehouse_inventory_form_url="https://forms.example/warehouse",
            technician_warehouse_inventory_form_token_secret=SecretStr(
                "wh-inv-sec-abc",
            ),
            technician_warehouse_inventory_form_token_entry_id="entry.3",
            token_field_name="token",
        ),
    )

    response = MagicMock()
    response.status = 200
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = response

    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    ops_logging = configure_ops_alert_logging(settings)
    assert ops_logging is not None

    try:
        logging.getLogger("src.infrastructure.outbox.worker").error(
            "Outbox handler revision_inventory failed for entry smoke-test-entry",
        )
    finally:
        ops_logging.stop()
        ops_logging.restore_exception_hooks()
        for handler in list(root_logger.handlers):
            if handler not in handlers_before:
                root_logger.removeHandler(handler)

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args.args[0]
    assert request.full_url == f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = json.loads(request.data.decode("utf-8"))
    assert payload["chat_id"] == admin_chat_id
    assert "ERROR mk_service_bot [prod]" in payload["text"]
    assert "logger: src.infrastructure.outbox.worker" in payload["text"]
    assert "Outbox handler revision_inventory failed for entry smoke-test-entry" in payload["text"]


@patch("src.infrastructure.alerting.telegram_log_handler.send_telegram_message")
def test_ops_alert_receives_uvicorn_error_despite_propagate_false(
    mock_send: MagicMock,
) -> None:
    """ASGI 500s log on uvicorn.error; parent uvicorn has propagate=False → not root."""
    logging.config.dictConfig(LOGGING_CONFIG)
    settings = _alert_settings(environment="prod", alert_chat_id=-1001)
    root_logger = logging.getLogger()
    uvicorn_error = logging.getLogger("uvicorn.error")
    root_handlers_before = list(root_logger.handlers)
    uvicorn_handlers_before = list(uvicorn_error.handlers)

    ops_logging = configure_ops_alert_logging(settings)
    assert ops_logging is not None

    try:
        uvicorn_error.error("Exception in ASGI application\n")
    finally:
        ops_logging.stop()
        ops_logging.restore_exception_hooks()
        for handler in list(root_logger.handlers):
            if handler not in root_handlers_before:
                root_logger.removeHandler(handler)
        for handler in list(uvicorn_error.handlers):
            if handler not in uvicorn_handlers_before:
                uvicorn_error.removeHandler(handler)

    mock_send.assert_called_once()
    assert "Exception in ASGI application" in mock_send.call_args.kwargs["text"]
    assert "logger: uvicorn.error" in mock_send.call_args.kwargs["text"]
