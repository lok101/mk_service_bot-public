from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class AiogramVisitForceNotifyTelegram:
    bot: Bot

    async def send_message(self, *, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)
