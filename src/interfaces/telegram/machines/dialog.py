from __future__ import annotations

from aiogram_dialog import Dialog, DialogManager
from beartype import beartype

from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.getters import build_machines_getter
from src.interfaces.telegram.machines.handlers import MachineListHandlers
from src.interfaces.telegram.machines.loading_photos_getter import (
    build_loading_photos_getter,
)
from src.interfaces.telegram.machines.loading_photos_window import (
    build_loading_photos_window,
)
from src.interfaces.telegram.machines.snack_inventory_window import (
    build_snack_inventory_window,
)
from src.interfaces.telegram.machines.windows import build_machines_list_window
from src.interfaces.telegram.machines.workspace_getter import build_workspace_getter
from src.interfaces.telegram.machines.workspace_window import build_workspace_window


async def on_machines_dialog_start(
    start_data: object,
    manager: DialogManager,
) -> None:
    if isinstance(start_data, dict):
        manager.dialog_data.update(start_data)


async def _empty_getter(**_kwargs: object) -> dict[str, object]:
    return {}


@beartype
def build_machines_dialog(deps: MachineListDeps) -> Dialog:
    handlers = MachineListHandlers(deps)
    machines_getter = build_machines_getter(deps)
    return Dialog(
        build_machines_list_window(handlers, machines_getter),
        build_workspace_window(handlers, build_workspace_getter(deps)),
        build_snack_inventory_window(handlers, _empty_getter),
        build_loading_photos_window(handlers, build_loading_photos_getter(deps)),
        on_start=on_machines_dialog_start,
    )
