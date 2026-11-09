from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from aiogram_dialog import StartMode
from aiogram_dialog.widgets.kbd import Select
from tests.interfaces._machine_list_handler_helpers import (
    TEST_BOT_USER,
    button,
    callback_query,
    caps,
)
from tests.interfaces._machine_list_handler_helpers import (
    handlers as make_handlers,
)

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import MaintenanceCompleted
from src.domain.models import VendingMachine
from src.domain.results import (
    LOADING_NOT_ALLOWED_REASON,
    MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    REVISION_NOT_ALLOWED_REASON,
    MaintenanceAlreadyCompletedToday,
    MaintenanceNotAllowed,
    maintenance_cooldown_reason,
)
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.contracts import TelegramMachineOption
from src.interfaces.telegram.machines.state import MachineListState

_UNKNOWN_USER_ALERT = "Не удалось найти пользователя."
_INACTIVE_USER_ALERT = "Ваша учётная запись неактивна. Обратитесь к администратору."
_UNKNOWN_TECHNICIAN_ALERT = "Не удалось найти техника."


def _select() -> Select[TelegramMachineOption]:
    return create_autospec(Select, instance=True)


async def _test_revision_stub_shows_revision_not_allowed_reason() -> None:
    handler = make_handlers()
    handler.deps.get_service_capabilities.execute.return_value = caps(
        can_complete_revision=False,
    )
    cb = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handler.on_revision_stub(cb, button(), manager)

    cb.answer.assert_awaited_once_with(
        REVISION_NOT_ALLOWED_REASON,
        show_alert=True,
    )


def test_revision_stub_shows_revision_not_allowed_reason() -> None:
    asyncio.run(_test_revision_stub_shows_revision_not_allowed_reason())


async def _test_loading_stub_shows_loading_not_allowed_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_submit_loading=False,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        LOADING_NOT_ALLOWED_REASON,
        show_alert=True,
    )


def test_loading_stub_shows_loading_not_allowed_reason() -> None:
    asyncio.run(_test_loading_stub_shows_loading_not_allowed_reason())


async def _test_complete_maintenance_stub_shows_maintenance_not_allowed_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        responsibility_phase="awaiting_handover",
        can_complete_maintenance=False,
        maintenance_completed_today=False,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_complete_maintenance_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        MAINTENANCE_NOT_ALLOWED_REASON,
        show_alert=True,
    )


def test_complete_maintenance_stub_shows_maintenance_not_allowed_reason() -> None:
    asyncio.run(_test_complete_maintenance_stub_shows_maintenance_not_allowed_reason())


async def _test_complete_maintenance_stub_shows_already_completed_today_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_complete_maintenance=False,
        maintenance_completed_today=True,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_complete_maintenance_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
        show_alert=True,
    )


def test_complete_maintenance_stub_shows_already_completed_today_reason() -> None:
    asyncio.run(_test_complete_maintenance_stub_shows_already_completed_today_reason())


async def _test_complete_maintenance_stub_shows_cooldown_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_complete_maintenance=False,
        can_submit_loading_photos=False,
        maintenance_completed_today=False,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_complete_maintenance_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        maintenance_cooldown_reason(20),
        show_alert=True,
    )


def test_complete_maintenance_stub_shows_cooldown_reason() -> None:
    asyncio.run(_test_complete_maintenance_stub_shows_cooldown_reason())


async def _test_revision_stub_unknown_user_shows_alert() -> None:
    handlers = make_handlers()
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=None),
    ):
        await handlers.on_revision_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        _UNKNOWN_USER_ALERT,
        show_alert=True,
    )


def test_revision_stub_unknown_user_shows_alert() -> None:
    asyncio.run(_test_revision_stub_unknown_user_shows_alert())


async def _test_revision_stub_inactive_user_shows_alert() -> None:
    handlers = make_handlers()
    inactive_user = SystemUser(
        user_id=SystemUserId("10002"),
        name="Inactive",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=1,
        technician_id=TechnicianId("001"),
        company_roles=frozenset(),
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=inactive_user),
    ):
        await handlers.on_revision_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        _INACTIVE_USER_ALERT,
        show_alert=True,
    )


def test_revision_stub_inactive_user_shows_alert() -> None:
    asyncio.run(_test_revision_stub_inactive_user_shows_alert())


async def _test_revision_stub_unknown_technician_shows_alert() -> None:
    handlers = make_handlers()
    user_without_technician = SystemUser(
        user_id=SystemUserId("10004"),
        name="NoTech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1,
        technician_id=None,
        company_roles=frozenset(),
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=user_without_technician),
    ):
        await handlers.on_revision_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        _UNKNOWN_TECHNICIAN_ALERT,
        show_alert=True,
    )


def test_revision_stub_unknown_technician_shows_alert() -> None:
    asyncio.run(_test_revision_stub_unknown_technician_shows_alert())


async def _test_machine_selected_switches_to_workspace() -> None:
    handlers = make_handlers()
    machine = VendingMachine(id=MachineId("vm-1"), name="VM 1")
    handlers.deps.vending_machine_repository.get.return_value = machine
    callback = callback_query(with_message=True)
    manager = MagicMock()
    manager.dialog_data = {}
    manager.switch_to = AsyncMock()

    with (
        patch(
            "src.interfaces.telegram.machines.handlers_selection.resolve_bot_user",
            new=AsyncMock(return_value=TEST_BOT_USER),
        ),
        patch(
            "src.interfaces.telegram.machines.handlers_selection.provision_workspace_links",
            new=AsyncMock(),
        ) as provision,
    ):
        await handlers.on_machine_selected(callback, _select(), manager, "vm-1")

    provision.assert_awaited_once()
    callback.answer.assert_awaited_once()
    manager.switch_to.assert_awaited_once_with(MachineListState.workspace)
    assert manager.dialog_data["machine_id"] == "vm-1"
    assert manager.dialog_data["machine_name"] == "VM 1"


def test_machine_selected_switches_to_workspace() -> None:
    asyncio.run(_test_machine_selected_switches_to_workspace())


async def _test_machine_selected_unknown_user_shows_alert() -> None:
    handlers = make_handlers()
    callback = callback_query(with_message=True)
    manager = MagicMock()
    manager.dialog_data = {}

    with patch(
        "src.interfaces.telegram.machines.handlers_selection.resolve_bot_user",
        new=AsyncMock(return_value=None),
    ):
        await handlers.on_machine_selected(callback, _select(), manager, "vm-1")

    callback.answer.assert_awaited_once_with(
        _UNKNOWN_USER_ALERT,
        show_alert=True,
    )


def test_machine_selected_unknown_user_shows_alert() -> None:
    asyncio.run(_test_machine_selected_unknown_user_shows_alert())


async def _test_machine_selected_inactive_user_shows_alert() -> None:
    handlers = make_handlers()
    inactive_user = SystemUser(
        user_id=SystemUserId("10005"),
        name="Inactive",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=1,
        technician_id=TechnicianId("001"),
        company_roles=frozenset(),
    )
    callback = callback_query(with_message=True)
    manager = MagicMock()
    manager.dialog_data = {}

    with patch(
        "src.interfaces.telegram.machines.handlers_selection.resolve_bot_user",
        new=AsyncMock(return_value=inactive_user),
    ):
        await handlers.on_machine_selected(callback, _select(), manager, "vm-1")

    callback.answer.assert_awaited_once_with(
        _INACTIVE_USER_ALERT,
        show_alert=True,
    )


def test_machine_selected_inactive_user_shows_alert() -> None:
    asyncio.run(_test_machine_selected_inactive_user_shows_alert())


async def _test_machine_selected_admin_without_technician_blocked() -> None:
    handlers = make_handlers()
    admin_user = SystemUser(
        user_id=SystemUserId("10003"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1,
        technician_id=None,
        company_roles=frozenset(),
    )
    callback = callback_query(with_message=True)
    manager = MagicMock()
    manager.dialog_data = {}

    with patch(
        "src.interfaces.telegram.machines.handlers_selection.resolve_bot_user",
        new=AsyncMock(return_value=admin_user),
    ):
        await handlers.on_machine_selected(callback, _select(), manager, "vm-1")

    callback.answer.assert_awaited_once_with(
        "Операции с аппаратом для этой учётной записи пока недоступны.",
        show_alert=True,
    )


def test_machine_selected_admin_without_technician_blocked() -> None:
    asyncio.run(_test_machine_selected_admin_without_technician_blocked())


async def _test_machine_selected_missing_chat_id() -> None:
    handlers = make_handlers()
    machine = VendingMachine(id=MachineId("vm-1"), name="VM 1")
    handlers.deps.vending_machine_repository.get.return_value = machine
    callback = callback_query(with_message=False)
    manager = MagicMock()
    manager.dialog_data = {}

    with patch(
        "src.interfaces.telegram.machines.handlers_selection.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_machine_selected(callback, _select(), manager, "vm-1")

    callback.answer.assert_awaited_once_with(
        "Сообщение недоступно.",
        show_alert=True,
    )


def test_machine_selected_missing_chat_id() -> None:
    asyncio.run(_test_machine_selected_missing_chat_id())


async def _test_maintenance_completed_starts_machine_list() -> None:
    handlers = make_handlers()
    now = datetime.now(tz=UTC)
    handlers.deps.complete_maintenance.execute.return_value = MaintenanceCompleted(
        event_id=EventId("event-1"),
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        completed_at=now,
        occurred_at=now,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    manager.start = AsyncMock()

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_maintenance_completed(callback, button(), manager)

    callback.answer.assert_awaited_once_with("Обслуживание завершено.")
    manager.start.assert_awaited_once()
    call_kwargs = manager.start.call_args.kwargs
    assert call_kwargs["mode"] is StartMode.RESET_STACK


def test_maintenance_completed_starts_machine_list() -> None:
    asyncio.run(_test_maintenance_completed_starts_machine_list())


async def _test_maintenance_completed_not_allowed() -> None:
    handlers = make_handlers()
    handlers.deps.complete_maintenance.execute.return_value = MaintenanceNotAllowed(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        reason="x",
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_maintenance_completed(callback, button(), manager)

    callback.answer.assert_awaited_once_with("x", show_alert=True)


def test_maintenance_completed_not_allowed() -> None:
    asyncio.run(_test_maintenance_completed_not_allowed())


async def _test_maintenance_completed_already_completed_today_shows_reason() -> None:
    handlers = make_handlers()
    handlers.deps.complete_maintenance.execute.return_value = MaintenanceAlreadyCompletedToday(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        reason=MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_maintenance_completed(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
        show_alert=True,
    )


def test_maintenance_completed_already_completed_today_shows_reason() -> None:
    asyncio.run(_test_maintenance_completed_already_completed_today_shows_reason())


async def _test_maintenance_completed_unexpected_result_shows_generic_alert() -> None:
    handlers = make_handlers()
    handlers.deps.complete_maintenance.execute.return_value = object()
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_maintenance.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_maintenance_completed(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        "Не удалось завершить обслуживание.",
        show_alert=True,
    )


def test_maintenance_completed_unexpected_result_shows_generic_alert() -> None:
    asyncio.run(_test_maintenance_completed_unexpected_result_shows_generic_alert())


async def _test_loading_photos_click_allowed_switches_state() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_submit_loading_photos=True,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    manager.switch_to = AsyncMock()

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_click(callback, button(), manager)

    callback.answer.assert_awaited_once()
    manager.switch_to.assert_awaited_once_with(MachineListState.loading_photos)


def test_loading_photos_click_allowed_switches_state() -> None:
    asyncio.run(_test_loading_photos_click_allowed_switches_state())


async def _test_back_to_machines_switches_state() -> None:
    handlers = make_handlers()
    callback = callback_query()
    manager = MagicMock()
    manager.switch_to = AsyncMock()

    await handlers.on_back_to_machines(callback, button(), manager)

    callback.answer.assert_awaited_once()
    manager.switch_to.assert_awaited_once_with(MachineListState.machines)


def test_back_to_machines_switches_state() -> None:
    asyncio.run(_test_back_to_machines_switches_state())
