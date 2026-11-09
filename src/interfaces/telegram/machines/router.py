from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode
from beartype import beartype

from src.application.machine_operations import LocationListScope
from src.interfaces.telegram.machines.deps import MachineDialogDeps
from src.interfaces.telegram.machines.location_scope import start_data_for_scope
from src.interfaces.telegram.machines.state import MachineListState
from src.interfaces.telegram.technician_warehouse import show_my_stock_inventory_form


async def _start_machine_list(
    dialog_manager: DialogManager,
    *,
    scope: LocationListScope,
) -> None:
    await dialog_manager.start(
        MachineListState.machines,
        mode=StartMode.RESET_STACK,
        data=start_data_for_scope(scope),
    )


@beartype
def build_machines_router(
    *,
    machine_dialog_deps: MachineDialogDeps | None = None,
) -> Router:
    router = Router(name="machines")

    @router.message(Command("start"))
    async def start_my_locations(
        message: Message,
        dialog_manager: DialogManager,
    ) -> None:
        _ = message
        await _start_machine_list(dialog_manager, scope=LocationListScope.OWN)

    @router.message(Command("other_locs"))
    async def start_other_locations(
        message: Message,
        dialog_manager: DialogManager,
    ) -> None:
        _ = message
        await _start_machine_list(dialog_manager, scope=LocationListScope.OTHERS)

    if machine_dialog_deps is not None:

        @router.message(Command("my_stock"))
        async def my_stock_inventory_form(message: Message) -> None:
            await show_my_stock_inventory_form(message, machine_dialog_deps)

    return router
