from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, create_autospec

from aiogram import Bot

from src.application.form_submissions.ports import TelegramUserResolver
from src.domain.ids import EventId, TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.interfaces.telegram.technician_warehouse_inventory_outbox import (
    TechnicianWarehouseInventoryTelegramHandler,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_TELEGRAM_USER_ID = 424242


def _active_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-1"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=_TECHNICIAN_ID,
        company_roles=frozenset(),
    )


def _success_handler(
    *, bot_user: SystemUser | None
) -> tuple[TechnicianWarehouseInventoryTelegramHandler, AsyncMock]:
    bot = create_autospec(Bot, instance=True)
    bot.send_message = AsyncMock()
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = bot_user
    handler = TechnicianWarehouseInventoryTelegramHandler(
        telegram_user_resolver=resolver,
        bot=bot,
    )
    return handler, bot


def _inventory_counted_event() -> TechnicianWarehouseInventoryCounted:
    occurred_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    return TechnicianWarehouseInventoryCounted(
        event_id=EventId("evt-wh-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=occurred_at,
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=occurred_at,
        lines=(("coffee", Decimal("1")),),
        baseline=True,
    )


def test_warehouse_inventory_telegram_message_is_stock_accepted() -> None:
    handler, bot = _success_handler(bot_user=_active_technician())
    asyncio.run(handler.process(_inventory_counted_event()))
    bot.send_message.assert_awaited_once_with(
        chat_id=_TELEGRAM_USER_ID,
        text="Остатки склада приняты.",
    )


def test_inventory_success_handler_skips_when_bot_user_missing() -> None:
    handler, bot = _success_handler(bot_user=None)
    asyncio.run(handler.process(_inventory_counted_event()))
    bot.send_message.assert_not_awaited()


def test_inventory_success_handler_does_not_touch_form_workflow() -> None:
    handler, _bot = _success_handler(bot_user=_active_technician())
    assert not hasattr(handler, "form_workflow_notifier")
