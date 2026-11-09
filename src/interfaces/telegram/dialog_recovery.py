from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.types.error_event import ErrorEvent
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.api.entities import ShowMode
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState
from beartype import beartype

from src.application.machine_operations import LocationListScope
from src.interfaces.telegram.machines.location_scope import start_data_for_scope
from src.interfaces.telegram.machines.state import MachineListState
from src.interfaces.telegram.stale_callback import handle_stale_callback_query

_LOGGER = logging.getLogger(__name__)


async def recover_stale_dialog(
    event: ErrorEvent,
    dialog_manager: DialogManager,
) -> None:
    """Reset dialog stack after removed/unknown FSM state or stale intent."""
    _LOGGER.warning(
        "Recovering dialog after %s: %s",
        type(event.exception).__name__,
        event.exception,
    )
    await dialog_manager.start(
        MachineListState.machines,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.SEND,
        data=start_data_for_scope(LocationListScope.OWN),
    )


@beartype
def register_dialog_recovery_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.errors.register(
        recover_stale_dialog,
        ExceptionTypeFilter(UnknownState, UnknownIntent),
    )
    dispatcher.errors.register(
        handle_stale_callback_query,
        ExceptionTypeFilter(TelegramBadRequest),
    )
