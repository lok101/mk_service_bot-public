from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from aiogram import Dispatcher
from aiogram.types.error_event import ErrorEvent
from aiogram_dialog import StartMode
from aiogram_dialog.api.entities import ShowMode
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState

from src.application.machine_operations import LocationListScope
from src.interfaces.telegram.dialog_recovery import (
    recover_stale_dialog,
    register_dialog_recovery_handlers,
)
from src.interfaces.telegram.machines.location_scope import LOCATION_SCOPE_KEY
from src.interfaces.telegram.machines.state import MachineListState


def test_recover_stale_dialog_restarts_machine_list_on_unknown_state() -> None:
    manager = MagicMock()
    manager.start = AsyncMock()
    event = MagicMock(spec=ErrorEvent)
    event.exception = UnknownState("Unknown state MachineListState:onboarding")

    asyncio.run(recover_stale_dialog(event, manager))

    manager.start.assert_awaited_once_with(
        MachineListState.machines,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.SEND,
        data={LOCATION_SCOPE_KEY: LocationListScope.OWN.value},
    )


def test_recover_stale_dialog_restarts_machine_list_on_unknown_intent() -> None:
    manager = MagicMock()
    manager.start = AsyncMock()
    event = MagicMock(spec=ErrorEvent)
    event.exception = UnknownIntent("Context not found for intent id: stale")

    asyncio.run(recover_stale_dialog(event, manager))

    manager.start.assert_awaited_once_with(
        MachineListState.machines,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.SEND,
        data={LOCATION_SCOPE_KEY: LocationListScope.OWN.value},
    )


def test_register_dialog_recovery_handlers_attaches_error_observer() -> None:
    dispatcher = Dispatcher()
    assert not dispatcher.errors.handlers

    register_dialog_recovery_handlers(dispatcher)

    assert len(dispatcher.errors.handlers) == 2
