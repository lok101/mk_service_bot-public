from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tests.interfaces._machine_list_handler_helpers import (
    TEST_BOT_USER,
    button,
    callback_query,
    handlers,
)

from src.application.snack_loading.issue_inventory_link import IssueSnackInventoryLink
from src.application.snack_loading.ports import InventoryFormCell
from src.infrastructure.testing.snack_loading_fakes import (
    FakeSnackInventoryCellsSource,
    FakeSnackInventoryFormFactory,
    FakeSnackInventoryFormsConfig,
    InMemorySnackInventoryFormRegistry,
)
from src.interfaces.telegram.machines.snack_inventory_workspace import NO_SNACK_MATRIX_MESSAGE
from src.interfaces.telegram.machines.state import MachineListState

_CELLS = (InventoryFormCell("SnackA", 1, "SKU1"),)
_ISSUED_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _issue_uc() -> IssueSnackInventoryLink:
    return IssueSnackInventoryLink(
        registry=InMemorySnackInventoryFormRegistry(),
        factory=FakeSnackInventoryFormFactory(),
        forms_settings=FakeSnackInventoryFormsConfig(),
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.snack",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=lambda: _ISSUED_AT,
        qty_max=30,
    )


def test_on_snack_inventory_now_sends_url_and_returns_workspace() -> None:
    async def _run() -> None:
        list_handlers = handlers()
        cells = FakeSnackInventoryCellsSource({"vm-1": _CELLS})
        object.__setattr__(list_handlers.deps, "issue_snack_inventory_link", _issue_uc())
        object.__setattr__(list_handlers.deps, "snack_inventory_cells", cells)

        callback = callback_query(with_message=True)
        callback.message.answer = AsyncMock()
        manager = MagicMock()
        manager.dialog_data = {"machine_id": "vm-1", "machine_name": "VM 1"}
        manager.switch_to = AsyncMock()

        with patch(
            "src.interfaces.telegram.machines.handlers_snack_inventory.resolve_bot_user",
            new=AsyncMock(return_value=TEST_BOT_USER),
        ):
            await list_handlers.on_snack_inventory_now(callback, button(), manager)

        callback.message.answer.assert_awaited()
        answer_kwargs = callback.message.answer.await_args.kwargs
        markup = answer_kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].url.startswith("https://")
        manager.switch_to.assert_awaited_once_with(MachineListState.workspace)

    asyncio.run(_run())


def test_on_snack_inventory_click_answers_when_issuer_missing() -> None:
    async def _run() -> None:
        list_handlers = handlers()
        object.__setattr__(list_handlers.deps, "issue_snack_inventory_link", None)
        object.__setattr__(
            list_handlers.deps,
            "snack_inventory_cells",
            FakeSnackInventoryCellsSource({"vm-1": _CELLS}),
        )

        callback = callback_query()
        manager = MagicMock()
        manager.dialog_data = {"machine_id": "vm-1", "machine_name": "VM 1"}
        manager.switch_to = AsyncMock()

        with patch(
            "src.interfaces.telegram.machines.handlers_snack_inventory.resolve_bot_user",
            new=AsyncMock(return_value=TEST_BOT_USER),
        ):
            await list_handlers.on_snack_inventory_click(callback, button(), manager)

        callback.answer.assert_awaited_once_with(NO_SNACK_MATRIX_MESSAGE, show_alert=True)
        manager.switch_to.assert_not_awaited()

    asyncio.run(_run())
