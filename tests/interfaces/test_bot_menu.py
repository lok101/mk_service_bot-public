from __future__ import annotations

from src.interfaces.telegram.bot_menu import default_bot_commands


def test_default_bot_commands_includes_my_stock() -> None:
    commands = {command.command: command.description for command in default_bot_commands()}
    assert commands["my_stock"] == "Инвентаризация склада"
