from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types.error_event import ErrorEvent

from src.interfaces.telegram.dialog_recovery import register_dialog_recovery_handlers
from src.interfaces.telegram.stale_callback import (
    handle_stale_callback_query,
    is_stale_callback_query_error,
)


def test_stale_callback_query_is_warning_not_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # error recovery
    exc = TelegramBadRequest(method=None, message="query is too old")
    assert is_stale_callback_query_error(exc) is True
    caplog.set_level(logging.WARNING)
    event = MagicMock(spec=ErrorEvent)
    event.exception = exc

    asyncio.run(handle_stale_callback_query(event))

    assert any("stale_telegram_callback_query" in r.getMessage() for r in caplog.records)
    assert all(r.levelno < logging.ERROR for r in caplog.records)


def test_invalid_query_id_is_stale() -> None:
    # edge
    exc = TelegramBadRequest(method=None, message="query ID is invalid")
    assert is_stale_callback_query_error(exc) is True


def test_other_telegram_bad_request_is_not_stale() -> None:
    # edge: не глотать
    exc = TelegramBadRequest(method=None, message="button_type_invalid")
    assert is_stale_callback_query_error(exc) is False


def test_register_stale_callback_handler() -> None:
    # happy
    dp = Dispatcher()
    register_dialog_recovery_handlers(dp)
    assert len(dp.errors.handlers) >= 2
