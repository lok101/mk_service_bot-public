from __future__ import annotations

import logging

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from beartype import beartype

from src.application.snack_loading.issue_inventory_link import IssuedSnackInventoryLink
from src.application.snack_loading.ports import SnackInventoryFormMode
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.dialog_data import get_selected_machine_id
from src.interfaces.telegram.machines.handlers_common import (
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
)
from src.interfaces.telegram.machines.snack_inventory_workspace import (
    NO_SNACK_MATRIX_MESSAGE,
    issue_snack_inventory_link_for_mode,
)
from src.interfaces.telegram.machines.state import MachineListState

_logger = logging.getLogger(__name__)
_ISSUE_FAILED_ALERT = "Не удалось выдать форму инвентаризации снека."


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class SnackInventoryHandlersMixin(CommonHandlersMixin):
    async def on_snack_inventory_click(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        if self.deps.issue_snack_inventory_link is None or self.deps.snack_inventory_cells is None:
            await callback.answer(NO_SNACK_MATRIX_MESSAGE, show_alert=True)
            return
        cells = self.deps.snack_inventory_cells.list_cells(machine_id.value)
        if not cells:
            await callback.answer(NO_SNACK_MATRIX_MESSAGE, show_alert=True)
            return
        await manager.switch_to(MachineListState.snack_inventory)

    async def on_snack_inventory_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button, manager
        await callback.answer(NO_SNACK_MATRIX_MESSAGE, show_alert=True)

    async def on_snack_inventory_now(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        await self._issue_snack_inventory_mode(callback, manager, mode="now")

    async def on_snack_inventory_as_of(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        await self._issue_snack_inventory_mode(callback, manager, mode="as_of")

    async def on_snack_inventory_back(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del callback, button
        await manager.switch_to(MachineListState.workspace)

    async def _issue_snack_inventory_mode(
        self,
        callback: CallbackQuery,
        manager: DialogManager,
        *,
        mode: SnackInventoryFormMode,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        issuer = self.deps.issue_snack_inventory_link
        cells_source = self.deps.snack_inventory_cells
        if issuer is None or cells_source is None:
            await callback.answer(NO_SNACK_MATRIX_MESSAGE, show_alert=True)
            return
        try:
            result = issue_snack_inventory_link_for_mode(
                machine_code=machine_id.value,
                mode=mode,
                technician_id=technician_id,
                cells_source=cells_source,
                issuer=issuer,
            )
        except Exception:
            _logger.exception(
                "snack_inventory_issue_failed",
                extra={"machine_code": machine_id.value, "mode": mode},
            )
            await callback.answer(_ISSUE_FAILED_ALERT, show_alert=True)
            return
        if isinstance(result, str):
            await callback.answer(result, show_alert=True)
            return
        await _send_inventory_url(callback, result)
        await manager.switch_to(MachineListState.workspace)


async def _send_inventory_url(
    callback: CallbackQuery,
    link: IssuedSnackInventoryLink,
) -> None:
    if callback.message is None:
        await callback.answer(link.form_url, show_alert=True)
        return
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть форму", url=link.form_url)],
        ],
    )
    await callback.message.answer(
        "Ссылка на инвентаризацию снека:",
        reply_markup=markup,
    )
    await callback.answer()
