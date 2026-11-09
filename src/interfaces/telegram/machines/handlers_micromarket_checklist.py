from __future__ import annotations

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from beartype import beartype

from src.interfaces.telegram.machines.handlers_common import (
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
)
from src.interfaces.telegram.machines.micromarket_field_checklist import (
    CHECKLIST_LOCKED_INVENTORY_MESSAGE,
    CHECKLIST_STEP_LOCKED_MESSAGE,
    try_advance_checklist,
)


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class MicromarketChecklistHandlersMixin(CommonHandlersMixin):
    async def on_mm_checklist_1_click(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        await self._advance_checklist(callback, manager, target_step=1)

    async def on_mm_checklist_2_click(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        await self._advance_checklist(callback, manager, target_step=2)

    async def on_mm_checklist_3_click(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button
        await self._advance_checklist(callback, manager, target_step=3)

    async def on_micromarket_inventory_checklist_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button, manager
        await callback.answer(CHECKLIST_LOCKED_INVENTORY_MESSAGE, show_alert=True)

    async def _advance_checklist(
        self,
        callback: CallbackQuery,
        manager: DialogManager,
        *,
        target_step: int,
    ) -> None:
        ok = try_advance_checklist(manager.dialog_data, target_step=target_step)
        if not ok:
            await callback.answer(CHECKLIST_STEP_LOCKED_MESSAGE, show_alert=True)
            return
        await callback.answer()
        await manager.show()
