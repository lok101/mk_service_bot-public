from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram_dialog.api.entities import ShowMode

from src.domain.ids import MachineId, TechnicianId
from src.interfaces.telegram.form_workflow import FormWorkflowSession
from src.interfaces.telegram.form_workflow_dialog import refresh_workspace_panel
from src.interfaces.telegram.machines.state import MachineListState


class _FakeContext:
    def __init__(self, state: object) -> None:
        self.state = state


class _FakeStack:
    def __init__(self, message_id: int | None) -> None:
        self.last_message_id = message_id


class _FakeDialogManager:
    def __init__(self, *, active_state: object, message_id: int | None = 42) -> None:
        self.dialog_data: dict[str, object] = {}
        self._active_state = active_state
        self._stack = _FakeStack(message_id)
        self.switch_states: list[object] = []
        self.show_modes: list[object] = []
        self.show_mode: object | None = None

    def has_context(self) -> bool:
        return True

    def current_context(self) -> _FakeContext:
        return _FakeContext(self._active_state)

    def current_stack(self) -> _FakeStack:
        return self._stack

    async def switch_to(self, state: object, /, **kwargs: object) -> None:
        _ = kwargs
        self.switch_states.append(state)
        self._active_state = state

    async def show(self, show_mode: object | None = None, /, **kwargs: object) -> None:
        _ = kwargs
        self.show_modes.append(show_mode)


class _FakeBgManager:
    def __init__(self, manager: _FakeDialogManager) -> None:
        self._manager = manager

    @asynccontextmanager
    async def fg(self) -> AsyncIterator[_FakeDialogManager]:
        yield self._manager


class _NoContextManager(_FakeDialogManager):
    def has_context(self) -> bool:
        return False


async def _test_refresh_workspace_panel_edits_without_switch() -> None:
    manager = _FakeDialogManager(active_state=MachineListState.workspace, message_id=100)
    bg = _FakeBgManager(manager)
    deps = MagicMock()
    session = FormWorkflowSession(
        chat_id=1,
        telegram_user_id=1,
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        machine_name="VM 1",
        purpose="revision",
        maintenance_screen="maintenance",
        registered_at=datetime.now(tz=UTC),
        dialog_message_id=55,
    )

    with patch(
        "src.interfaces.telegram.form_workflow_dialog.provision_workspace_links",
    ) as provision:
        updated = await refresh_workspace_panel(
            bg,
            deps,
            session=session,
            form_error="ошибка токена",
            refresh_links=False,
        )

    assert updated is True
    assert manager.switch_states == []
    assert manager.show_modes == [ShowMode.EDIT]
    assert manager.show_mode == ShowMode.EDIT
    assert manager.dialog_data["machine_id"] == "vm-1"
    assert manager.dialog_data["form_workflow_error"] == "ошибка токена"
    provision.assert_not_called()


async def _test_refresh_workspace_panel_provision_on_accepted() -> None:
    manager = _FakeDialogManager(active_state=MachineListState.workspace)
    bg = _FakeBgManager(manager)
    deps = MagicMock()
    session = FormWorkflowSession(
        chat_id=1,
        telegram_user_id=1,
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        machine_name="VM 1",
        purpose="revision",
        maintenance_screen="maintenance",
        registered_at=datetime.now(tz=UTC),
        dialog_message_id=99,
    )

    with patch(
        "src.interfaces.telegram.form_workflow_dialog.provision_workspace_links",
        new=AsyncMock(),
    ) as provision:
        await refresh_workspace_panel(
            bg,
            deps,
            session=session,
            refresh_links=True,
        )

    provision.assert_called_once()
    assert provision.call_args.kwargs["machine_id"] == MachineId("vm-1")


async def _test_refresh_workspace_panel_no_context() -> None:
    manager = _NoContextManager(active_state=MachineListState.workspace)
    bg = _FakeBgManager(manager)

    updated = await refresh_workspace_panel(
        bg,
        MagicMock(),
        session=FormWorkflowSession(
            chat_id=1,
            telegram_user_id=1,
            technician_id=TechnicianId("001"),
            machine_id=MachineId("vm-1"),
            machine_name="VM 1",
            purpose="revision",
            maintenance_screen="maintenance",
            registered_at=datetime.now(tz=UTC),
        ),
    )

    assert updated is False
    assert manager.show_modes == []


def test_refresh_workspace_panel_edits_without_switch() -> None:
    asyncio.run(_test_refresh_workspace_panel_edits_without_switch())


def test_refresh_workspace_panel_provision_on_accepted() -> None:
    asyncio.run(_test_refresh_workspace_panel_provision_on_accepted())


def test_refresh_workspace_panel_no_context() -> None:
    asyncio.run(_test_refresh_workspace_panel_no_context())
