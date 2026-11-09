from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch
from urllib.parse import parse_qs, urlparse

from aiogram.types import Message

from src.domain.form_tokens import (
    verify_technician_warehouse_inventory_token,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.integrations.google.forms.link_providers import (
    GoogleFormsTechnicianWarehouseInventoryLinkProvider,
    UnconfiguredTechnicianWarehouseInventoryLinkProvider,
)
from src.interfaces.telegram.machines.deps import MachineDialogDeps
from src.interfaces.telegram.technician_warehouse import show_my_stock_inventory_form

_WAREHOUSE_SECRET = "warehouse-secret"
_WAREHOUSE_FORM_URL = "https://docs.google.com/forms/d/warehouse/viewform"
_WAREHOUSE_ENTRY_ID = "entry.999"
_TECHNICIAN_ID = TechnicianId("tech-1")
_TELEGRAM_USER_ID = 424242


def _active_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-1"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=_TECHNICIAN_ID,
        company_roles=frozenset(),
    )


def _inactive_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-1"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=_TECHNICIAN_ID,
        company_roles=frozenset(),
    )


def _admin_without_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("admin-1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_TELEGRAM_USER_ID,
        technician_id=None,
        company_roles=frozenset(),
    )


def _command_case(user: SystemUser | None) -> tuple[Message, MachineDialogDeps]:
    message = create_autospec(Message, instance=True)
    message.from_user = MagicMock(id=_TELEGRAM_USER_ID)
    message.answer = AsyncMock()
    deps = MagicMock(spec=MachineDialogDeps)
    deps.technician_warehouse_inventory_link_provider.create_link.return_value = MagicMock(
        url=f"{_WAREHOUSE_FORM_URL}?{_WAREHOUSE_ENTRY_ID}=token",
    )
    return message, deps


def _run_my_stock(user: SystemUser | None, message: Message, deps: MachineDialogDeps) -> None:
    with patch(
        "src.interfaces.telegram.technician_warehouse.resolve_bot_user",
        new=AsyncMock(return_value=user),
    ):
        asyncio.run(show_my_stock_inventory_form(message, deps))


def _extract_prefilled_value(url: str, entry_id: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query[entry_id][0]


def test_my_stock_known_technician_sends_one_url_button() -> None:
    message, deps = _command_case(_active_technician())
    _run_my_stock(_active_technician(), message, deps)
    message.answer.assert_awaited_once()
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 1
    assert len(markup.inline_keyboard[0]) == 1
    assert markup.inline_keyboard[0][0].url is not None


def test_my_stock_unknown_user_refuses_without_url() -> None:
    message, deps = _command_case(None)
    _run_my_stock(None, message, deps)
    assert message.answer.await_args.args[0] == "Не удалось определить склад техника."
    assert message.answer.await_args.kwargs.get("reply_markup") is None


def test_my_stock_inactive_user_refuses_without_url() -> None:
    message, deps = _command_case(_inactive_technician())
    _run_my_stock(_inactive_technician(), message, deps)
    assert message.answer.await_args.args[0] == "Не удалось определить склад техника."
    assert message.answer.await_args.kwargs.get("reply_markup") is None


def test_my_stock_user_without_technician_id_refuses_without_url() -> None:
    message, deps = _command_case(_admin_without_technician())
    _run_my_stock(_admin_without_technician(), message, deps)
    assert message.answer.await_args.args[0] == "Не удалось определить склад техника."
    assert message.answer.await_args.kwargs.get("reply_markup") is None


def test_my_stock_link_uses_warehouse_inventory_form_settings() -> None:
    provider = GoogleFormsTechnicianWarehouseInventoryLinkProvider(
        form_url=_WAREHOUSE_FORM_URL,
        token_entry_id=_WAREHOUSE_ENTRY_ID,
        token_secret=_WAREHOUSE_SECRET,
        clock=lambda: datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )
    link = provider.create_link(TechnicianId("tech-1"))
    assert link.url.startswith(_WAREHOUSE_FORM_URL)
    assert _WAREHOUSE_ENTRY_ID in link.url
    token = _extract_prefilled_value(link.url, _WAREHOUSE_ENTRY_ID)
    payload = verify_technician_warehouse_inventory_token(token, _WAREHOUSE_SECRET)
    assert payload.technician_id == TechnicianId("tech-1")


def test_my_stock_unconfigured_form_refuses_without_url_button() -> None:
    message = create_autospec(Message, instance=True)
    message.from_user = MagicMock(id=_TELEGRAM_USER_ID)
    message.answer = AsyncMock()
    deps = MagicMock(spec=MachineDialogDeps)
    deps.technician_warehouse_inventory_link_provider = (
        UnconfiguredTechnicianWarehouseInventoryLinkProvider()
    )
    _run_my_stock(_active_technician(), message, deps)
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == ("Форма инвентаризации склада не настроена.")
    assert message.answer.await_args.kwargs.get("reply_markup") is None
