from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from aiogram import Bot

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.form_workflow.models import (
    FormWorkflowAccepted,
    FormWorkflowIntegrationFailed,
    FormWorkflowInvalid,
    FormWorkflowRejected,
)
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.telegram.contracts import TelegramDialogBackgroundFactory
from src.interfaces.telegram.form_workflow import FormWorkflowSession
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.form_workflow_notifier import (
    NoOpFormWorkflowNotifier,
    TelegramFormWorkflowNotifier,
)
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.form_workflow_error import format_form_error_block


def _session(*, purpose: str = "revision") -> FormWorkflowSession:
    return FormWorkflowSession(
        chat_id=12345,
        telegram_user_id=1,
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        machine_name="VM 1",
        purpose=purpose,  # type: ignore[arg-type]
        maintenance_screen="maintenance",
        registered_at=datetime.now(tz=UTC),
    )


def _notifier(
    *,
    session_store: FormWorkflowSessionStore | None = None,
    bot: Bot | None = None,
    telegram_user_resolver: TelegramUserResolver | None = None,
) -> TelegramFormWorkflowNotifier:
    store = session_store or create_autospec(FormWorkflowSessionStore, instance=True)
    bot_mock = bot or _bot()
    resolver = telegram_user_resolver or create_autospec(TelegramUserResolver, instance=True)
    return TelegramFormWorkflowNotifier(
        bot=bot_mock,
        session_store=store,
        telegram_user_resolver=resolver,
        dialog_bg_factory=create_autospec(TelegramDialogBackgroundFactory, instance=True),
        machine_list_deps=create_autospec(MachineListDeps, instance=True),
    )


def _bot() -> Bot:
    mock = create_autospec(Bot, instance=True)
    mock.send_message = AsyncMock()
    return mock


class _FakeBgManager:
    @asynccontextmanager
    async def fg(self) -> AsyncIterator[MagicMock]:
        yield MagicMock()


def _wire_bg_factory(notifier: TelegramFormWorkflowNotifier) -> None:
    notifier.dialog_bg_factory.bg.return_value = _FakeBgManager()


async def _test_notify_accepted_refreshes_workspace_and_clears_session() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = _session()
    bot = _bot()
    notifier = _notifier(session_store=store, bot=bot)
    _wire_bg_factory(notifier)
    outcome = FormWorkflowAccepted(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
    )

    with patch(
        "src.interfaces.telegram.form_workflow_notifier.refresh_workspace_panel",
        new=AsyncMock(return_value=True),
    ) as refresh:
        await notifier.notify(outcome)

    store.remove.assert_called_once_with(
        TechnicianId("001"),
        MachineId("vm-1"),
        "revision",
    )
    bot.send_message.assert_not_called()
    refresh.assert_awaited_once()


def test_notify_accepted_refreshes_workspace_and_clears_session() -> None:
    asyncio.run(_test_notify_accepted_refreshes_workspace_and_clears_session())


async def _test_notify_rejected_sends_chat_message() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = _session()
    bot = _bot()
    notifier = _notifier(session_store=store, bot=bot)
    _wire_bg_factory(notifier)
    outcome = FormWorkflowRejected(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
        detail="Нужна предзагрузка",
    )

    with patch(
        "src.interfaces.telegram.form_workflow_notifier.refresh_workspace_panel",
        new=AsyncMock(return_value=True),
    ):
        await notifier.notify(outcome)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Форма не принята" in text


def test_notify_rejected_sends_chat_message() -> None:
    asyncio.run(_test_notify_rejected_sends_chat_message())


async def _test_notify_integration_failed_sends_chat_message() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = _session(purpose="loading")
    bot = _bot()
    notifier = _notifier(session_store=store, bot=bot)
    _wire_bg_factory(notifier)
    outcome = FormWorkflowIntegrationFailed(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="loading",
        detail="МойСклад недоступен",
    )

    with patch(
        "src.interfaces.telegram.form_workflow_notifier.refresh_workspace_panel",
        new=AsyncMock(return_value=True),
    ):
        await notifier.notify(outcome)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Ошибка обработки ответа" in text


def test_notify_integration_failed_sends_chat_message() -> None:
    asyncio.run(_test_notify_integration_failed_sends_chat_message())


async def _test_notify_invalid_with_purpose_shows_form_error_in_window() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = _session()
    bot = _bot()
    notifier = _notifier(session_store=store, bot=bot)
    _wire_bg_factory(notifier)
    outcome = FormWorkflowInvalid(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
        detail="Revision form token has expired",
    )

    with patch(
        "src.interfaces.telegram.form_workflow_notifier.refresh_workspace_panel",
        new=AsyncMock(return_value=True),
    ) as refresh:
        await notifier.notify(outcome)

    refresh.assert_awaited_once()
    assert refresh.call_args.kwargs["form_error"] == "Revision form token has expired"
    bot.send_message.assert_not_called()


def test_notify_invalid_with_purpose_shows_form_error_in_window() -> None:
    asyncio.run(_test_notify_invalid_with_purpose_shows_form_error_in_window())


async def _test_notify_invalid_without_purpose_sends_chat_only() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = None
    bot = _bot()
    resolver = create_autospec(TelegramUserResolver, instance=True)
    bot_user = MagicMock()
    bot_user.telegram_user_id = 99999
    resolver.find_by_technician_id.return_value = bot_user
    notifier = _notifier(session_store=store, bot=bot, telegram_user_resolver=resolver)
    outcome = FormWorkflowInvalid(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose=None,
        detail="Токен недействителен",
    )

    await notifier.notify(outcome)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Токен недействителен" in text


def test_notify_invalid_without_purpose_sends_chat_only() -> None:
    asyncio.run(_test_notify_invalid_without_purpose_sends_chat_only())


async def _test_notify_skipped_when_no_chat_id() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = None
    bot = _bot()
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = None
    notifier = _notifier(session_store=store, bot=bot, telegram_user_resolver=resolver)
    outcome = FormWorkflowRejected(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="loading",
        detail="rejected",
    )

    await notifier.notify(outcome)

    bot.send_message.assert_not_called()


def test_notify_skipped_when_no_chat_id() -> None:
    asyncio.run(_test_notify_skipped_when_no_chat_id())


async def _test_notify_send_message_failure_is_swallowed() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = _session(purpose="loading")
    bot = _bot()
    bot.send_message.side_effect = RuntimeError("network down")
    notifier = _notifier(session_store=store, bot=bot)
    _wire_bg_factory(notifier)
    outcome = FormWorkflowRejected(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="loading",
        detail="rejected",
    )

    with patch(
        "src.interfaces.telegram.form_workflow_notifier.refresh_workspace_panel",
        new=AsyncMock(return_value=True),
    ):
        await notifier.notify(outcome)


def test_notify_send_message_failure_is_swallowed() -> None:
    asyncio.run(_test_notify_send_message_failure_is_swallowed())


async def _test_noop_notifier_does_nothing() -> None:
    notifier = NoOpFormWorkflowNotifier()
    outcome = FormWorkflowAccepted(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
    )

    await notifier.notify(outcome)


def test_noop_notifier_does_nothing() -> None:
    asyncio.run(_test_noop_notifier_does_nothing())


async def _test_notify_invalid_with_purpose_sends_fallback_when_refresh_fails() -> None:
    store = create_autospec(FormWorkflowSessionStore, instance=True)
    store.find.return_value = _session()
    bot = _bot()
    notifier = _notifier(session_store=store, bot=bot)
    _wire_bg_factory(notifier)
    outcome = FormWorkflowInvalid(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
        detail="Revision form token has expired",
    )

    with patch(
        "src.interfaces.telegram.form_workflow_notifier.refresh_workspace_panel",
        new=AsyncMock(return_value=False),
    ) as refresh:
        await notifier.notify(outcome)

    refresh.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert text == format_form_error_block("Revision form token has expired")


def test_notify_invalid_with_purpose_sends_fallback_when_refresh_fails() -> None:
    asyncio.run(_test_notify_invalid_with_purpose_sends_fallback_when_refresh_fails())
