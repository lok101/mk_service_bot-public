from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from beartype import beartype

from src.application.form_submissions.ports import TelegramUserResolver
from src.domain.ids import TechnicianId

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class TelegramDirectWarehouseChatNotifier:
    bot: Bot
    telegram_user_resolver: TelegramUserResolver

    @beartype
    async def notify(self, *, technician_id: TechnicianId, reason: str) -> None:
        bot_user = await asyncio.to_thread(
            self.telegram_user_resolver.find_by_technician_id,
            technician_id,
        )
        if bot_user is None:
            _LOGGER.warning(
                "direct_warehouse_chat_skipped_missing_bot_user",
                extra={"technician_id": technician_id.value},
            )
            return
        await self.bot.send_message(chat_id=bot_user.telegram_user_id, text=reason)
