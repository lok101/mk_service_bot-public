from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import ScrollingGroup, Select
from aiogram_dialog.widgets.text import Format

from src.interfaces.telegram.contracts import TelegramMachineOption
from src.interfaces.telegram.machines.handlers import MachineListHandlers
from src.interfaces.telegram.machines.labels import machine_option_id
from src.interfaces.telegram.machines.state import MachineListState


def build_machines_list_window(
    handlers: MachineListHandlers,
    getter: Callable[..., Awaitable[dict[str, object]]],
) -> Window:
    return Window(
        Format("{machines_screen_text}"),
        ScrollingGroup(
            Select[TelegramMachineOption](
                Format("{item.name}"),
                id="machine",
                item_id_getter=machine_option_id,
                items="machines",
                on_click=handlers.on_machine_selected,
            ),
            id="machines_pages",
            width=1,
            height=10,
            when="has_machines",
        ),
        getter=getter,
        state=MachineListState.machines,
    )
