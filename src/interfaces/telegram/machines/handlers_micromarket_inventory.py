from __future__ import annotations

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from beartype import beartype

from src.interfaces.telegram.machines.handlers_common import (
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
)
from src.interfaces.telegram.machines.workspace_links import (
    _MICROMARKET_INVENTORY_ISSUE_ERROR_KEY,
)

_ISSUE_FAILED_ALERT = "Не удалось выдать форму инвентаризации."
_NOT_CONFIGURED = "Инвентаризация микромаркета не настроена."


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class MicromarketInventoryHandlersMixin(CommonHandlersMixin):
    async def on_micromarket_inventory_click(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        """Alert path when getter could not put a Url on the workspace button (ISS-017)."""
        del button
        error = manager.dialog_data.get(_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY)
        if isinstance(error, str) and error.strip():
            await callback.answer(error, show_alert=True)
            return
        await callback.answer(_ISSUE_FAILED_ALERT, show_alert=True)

    async def on_micromarket_inventory_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        del button, manager
        await callback.answer(_NOT_CONFIGURED, show_alert=True)
