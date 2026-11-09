from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from beartype import beartype

from src.application.form_submissions.ports import TelegramUserResolver
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseInventoryTelegramHandler:
    telegram_user_resolver: TelegramUserResolver
    bot: Bot

    @beartype
    async def process(self, event: TechnicianWarehouseInventoryCounted) -> None:
        bot_user = await asyncio.to_thread(
            self.telegram_user_resolver.find_by_technician_id,
            event.technician_id,
        )
        if bot_user is None:
            _LOGGER.warning(
                "technician_warehouse_inventory_telegram_skipped_missing_bot_user",
                extra={"technician_id": event.technician_id.value},
            )
            return

        await self.bot.send_message(
            chat_id=bot_user.telegram_user_id,
            text="Остатки склада приняты.",
        )
