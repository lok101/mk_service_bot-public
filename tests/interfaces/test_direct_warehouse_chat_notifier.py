from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, create_autospec

import pytest
from aiogram import Bot

from src.application.form_submissions.ports import TelegramUserResolver
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.direct_warehouse_chat_notifier import (
    TelegramDirectWarehouseChatNotifier,
)

_TECH = TechnicianId("tech-chat-1")


def _bot_user() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-chat-1"),
        name="Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=42,
        technician_id=_TECH,
        company_roles=frozenset(),
    )


def _notifier(
    *,
    bot_user: SystemUser | None,
) -> tuple[TelegramDirectWarehouseChatNotifier, AsyncMock]:
    bot = create_autospec(Bot, instance=True)
    bot.send_message = AsyncMock()
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = bot_user
    notifier = TelegramDirectWarehouseChatNotifier(
        bot=bot,
        telegram_user_resolver=resolver,
    )
    return notifier, bot


def test_telegram_direct_warehouse_chat_notifier_sends_reason() -> None:
    notifier, bot = _notifier(bot_user=_bot_user())
    asyncio.run(notifier.notify(technician_id=_TECH, reason="warehouse error: conflict"))
    bot.send_message.assert_awaited_once_with(
        chat_id=42,
        text="warehouse error: conflict",
    )


def test_telegram_direct_warehouse_chat_notifier_skips_missing_bot_user(
    caplog: pytest.LogCaptureFixture,
) -> None:
    notifier, bot = _notifier(bot_user=None)
    with caplog.at_level(logging.WARNING):
        asyncio.run(notifier.notify(technician_id=_TECH, reason="ignored"))
    bot.send_message.assert_not_awaited()
    assert any(
        "direct_warehouse_chat_skipped_missing_bot_user" in r.getMessage() for r in caplog.records
    )
