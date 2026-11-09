from __future__ import annotations

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button, Select
from beartype import beartype

from src.domain.ids import MachineId
from src.interfaces.telegram.contracts import TelegramMachineOption
from src.interfaces.telegram.machines.access import (
    can_use_bot,
    requires_revision_check_before_maintenance,
)
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.handlers_common import (
    _INACTIVE_USER_ALERT,
    _UNKNOWN_USER_ALERT,
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
    _callback_chat_id,
    _dialog_message_id,
)
from src.interfaces.telegram.machines.micromarket_field_checklist import (
    clear_checklist_progress,
    sync_checklist_machine,
)
from src.interfaces.telegram.machines.state import MachineListState
from src.interfaces.telegram.machines.workspace_links import provision_workspace_links


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class SelectionHandlersMixin(CommonHandlersMixin):
    async def on_machine_selected(
        self,
        callback: CallbackQuery,
        widget: Select[TelegramMachineOption],
        manager: DialogManager,
        item_id: str,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        if bot_user is None:
            await callback.answer(_UNKNOWN_USER_ALERT, show_alert=True)
            return
        if not can_use_bot(bot_user):
            await callback.answer(_INACTIVE_USER_ALERT, show_alert=True)
            return

        machine_id = MachineId(item_id)
        sync_checklist_machine(manager.dialog_data, machine_id=machine_id.value)
        manager.dialog_data["machine_id"] = machine_id.value
        machine = self.deps.vending_machine_repository.get(machine_id)
        machine_name = machine.name if machine is not None else item_id
        manager.dialog_data["machine_name"] = machine_name

        if not requires_revision_check_before_maintenance(bot_user):
            await callback.answer(
                "Операции с аппаратом для этой учётной записи пока недоступны.",
                show_alert=True,
            )
            return

        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return

        chat_id = _callback_chat_id(callback)
        if chat_id is None:
            await callback.answer("Сообщение недоступно.", show_alert=True)
            return

        manager.dialog_data.pop("form_workflow_error", None)
        await provision_workspace_links(
            self.deps,
            manager=manager,
            chat_id=chat_id,
            telegram_user_id=callback.from_user.id,
            technician_id=technician_id,
            machine_id=machine_id,
            dialog_message_id=_dialog_message_id(callback),
            bot_user=bot_user,
        )
        await callback.answer()
        await manager.switch_to(MachineListState.workspace)

    async def on_back_to_machines(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        clear_checklist_progress(manager.dialog_data)
        await callback.answer()
        await manager.switch_to(MachineListState.machines)
