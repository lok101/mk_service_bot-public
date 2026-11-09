from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand
from beartype import beartype


@beartype
def default_bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Мои локации"),
        BotCommand(command="other_locs", description="Чужие локации"),
        BotCommand(command="my_stock", description="Инвентаризация склада"),
    ]


@beartype
async def register_bot_menu(bot: Bot) -> None:
    await bot.set_my_commands(default_bot_commands())
