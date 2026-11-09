from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Button
from aiogram_dialog.widgets.text import Const

from src.interfaces.telegram.machines.handlers import MachineListHandlers
from src.interfaces.telegram.machines.state import MachineListState


def build_snack_inventory_window(
    handlers: MachineListHandlers,
    getter: Callable[..., Awaitable[dict[str, object]]],
) -> Window:
    return Window(
        Const("Выберите режим инвентаризации снека:"),
        Button(
            Const("Сейчас (now)"),
            id="snack_inventory_now",
            on_click=handlers.on_snack_inventory_now,
        ),
        Button(
            Const("Задним числом (as_of)"),
            id="snack_inventory_as_of",
            on_click=handlers.on_snack_inventory_as_of,
        ),
        Button(
            Const("Назад"),
            id="snack_inventory_back",
            on_click=handlers.on_snack_inventory_back,
        ),
        getter=getter,
        state=MachineListState.snack_inventory,
    )
