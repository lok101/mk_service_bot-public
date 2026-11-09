from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from tests.interfaces._machine_list_handler_helpers import button, callback_query, handlers

from src.interfaces.telegram.machines.workspace_links import (
    _MICROMARKET_INVENTORY_ISSUE_ERROR_KEY,
)


async def _test_click_alerts_stored_issue_error() -> None:
    # edge: getter failed to issue → button click shows alert, no second message
    list_handlers = handlers()
    callback = callback_query(with_message=True)
    callback.message.answer = AsyncMock()
    manager = MagicMock()
    manager.dialog_data = {_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY: "нет SKU для инвентаризации"}

    await list_handlers.on_micromarket_inventory_click(callback, button(), manager)

    callback.message.answer.assert_not_awaited()
    callback.answer.assert_awaited_once_with("нет SKU для инвентаризации", show_alert=True)


def test_click_alerts_stored_issue_error() -> None:
    asyncio.run(_test_click_alerts_stored_issue_error())
