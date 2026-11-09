from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from aiogram.types import Message
from aiogram_dialog.widgets.input import MessageInput
from tests.interfaces._machine_list_handler_helpers import (
    TEST_BOT_USER,
    button,
    callback_query,
    caps,
)
from tests.interfaces._machine_list_handler_helpers import (
    handlers as make_handlers,
)

from src.application.photo_batches.errors import PhotoBatchRejectedError
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.results import (
    LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    LOADING_PHOTOS_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_REQUIRE_LOADING_REASON,
    maintenance_cooldown_reason,
)
from src.interfaces.telegram.machines.loading_photos_dialog_data import (
    append_photo,
    get_photo_index,
    init_loading_photos_session,
    photo_count,
    set_photo_index,
)
from src.interfaces.telegram.machines.state import MachineListState


def _message_input() -> MessageInput:
    return create_autospec(MessageInput, instance=True)


async def _test_loading_photos_stub_shows_already_submitted_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_submit_loading_photos=False,
        loading_photos_completed=True,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
        show_alert=True,
    )


def test_loading_photos_stub_shows_already_submitted_reason() -> None:
    asyncio.run(_test_loading_photos_stub_shows_already_submitted_reason())


async def _test_loading_photos_stub_shows_require_loading_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_submit_loading_photos=False,
        loading_completed=False,
        loading_photos_completed=False,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        LOADING_PHOTOS_REQUIRE_LOADING_REASON,
        show_alert=True,
    )


def test_loading_photos_stub_shows_require_loading_reason() -> None:
    asyncio.run(_test_loading_photos_stub_shows_require_loading_reason())


async def _test_loading_photos_stub_shows_not_allowed_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_submit_loading_photos=False,
        loading_completed=True,
        loading_photos_completed=False,
        can_complete_maintenance=True,
        maintenance_completed_today=True,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        LOADING_PHOTOS_NOT_ALLOWED_REASON,
        show_alert=True,
    )


def test_loading_photos_stub_shows_not_allowed_reason() -> None:
    asyncio.run(_test_loading_photos_stub_shows_not_allowed_reason())


async def _test_loading_photos_stub_shows_cooldown_reason() -> None:
    handlers = make_handlers()
    handlers.deps.get_service_capabilities.execute.return_value = caps(
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        maintenance_completed_today=False,
    )
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        maintenance_cooldown_reason(20),
        show_alert=True,
    )


def test_loading_photos_stub_shows_cooldown_reason() -> None:
    asyncio.run(_test_loading_photos_stub_shows_cooldown_reason())


async def _test_loading_photos_send_stub_requires_minimum() -> None:
    handlers = make_handlers()
    callback = callback_query()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}

    await handlers.on_loading_photos_send_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        "Нужно минимум 2 фотографий.",
        show_alert=True,
    )


def test_loading_photos_send_stub_requires_minimum() -> None:
    asyncio.run(_test_loading_photos_send_stub_requires_minimum())


async def _test_loading_photos_send_calls_accept_service() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    append_photo(
        manager,
        file_id="file-2",
        file_unique_id="unique-2",
        message_id=2,
    )
    batch_id = manager.dialog_data["loading_photos_batch_id"]

    handlers.deps.accept_loading_photos.execute.return_value = PhotosSubmitted(
        event_id=EventId("event-1"),
        batch_id=BatchId(batch_id),
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        photo_count=2,
        submitted_at=datetime.now(tz=UTC),
        occurred_at=datetime.now(tz=UTC),
    )

    callback = callback_query()
    manager.switch_to = AsyncMock()

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_send(callback, button(), manager)

    handlers.deps.accept_loading_photos.execute.assert_called_once()
    callback.answer.assert_awaited_once_with("Фото отправлены.")
    manager.switch_to.assert_awaited_once()


def test_loading_photos_send_calls_accept_service() -> None:
    asyncio.run(_test_loading_photos_send_calls_accept_service())


async def _test_loading_photos_send_shows_rejection_reason() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    append_photo(
        manager,
        file_id="file-2",
        file_unique_id="unique-2",
        message_id=2,
    )
    handlers.deps.accept_loading_photos.execute.side_effect = PhotoBatchRejectedError(
        "rejected",
    )

    callback = callback_query()

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_send(callback, button(), manager)

    callback.answer.assert_awaited_once_with("rejected", show_alert=True)


def test_loading_photos_send_shows_rejection_reason() -> None:
    asyncio.run(_test_loading_photos_send_shows_rejection_reason())


async def _test_loading_photos_photo_received_rejects_when_at_max() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    for index in range(10):
        append_photo(
            manager,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )

    message = create_autospec(Message, instance=True)
    message.photo = [MagicMock(file_id="file-extra", file_unique_id="unique-extra")]
    message.message_id = 99
    message.media_group_id = None
    message.answer = AsyncMock()

    await handlers.on_loading_photos_photo_received(message, _message_input(), manager)

    message.answer.assert_awaited_once_with("Максимум 10 фотографий.")
    assert photo_count(manager) == 10


def test_loading_photos_photo_received_rejects_when_at_max() -> None:
    asyncio.run(_test_loading_photos_photo_received_rejects_when_at_max())


async def _test_loading_photos_handlers_micromarket_rejects_third_photo() -> None:
    # error: MM max=2 — third photo alert, draft unchanged
    handlers = make_handlers()
    kind_lookup = MagicMock()
    kind_lookup.kind_of.return_value = "micro_market"
    object.__setattr__(handlers.deps, "machine_kind_lookup", kind_lookup)
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "701"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    append_photo(
        manager,
        file_id="file-2",
        file_unique_id="unique-2",
        message_id=2,
    )

    message = create_autospec(Message, instance=True)
    message.photo = [MagicMock(file_id="file-3", file_unique_id="unique-3")]
    message.message_id = 3
    message.media_group_id = None
    message.answer = AsyncMock()

    await handlers.on_loading_photos_photo_received(message, _message_input(), manager)

    message.answer.assert_awaited_once_with("Максимум 2 фотографий.")
    assert photo_count(manager) == 2


def test_loading_photos_handlers_micromarket_rejects_third_photo() -> None:
    asyncio.run(_test_loading_photos_handlers_micromarket_rejects_third_photo())


async def _test_loading_photos_handlers_micromarket_insufficient_send() -> None:
    # error: MM send with <2 → insufficient alert
    handlers = make_handlers()
    kind_lookup = MagicMock()
    kind_lookup.kind_of.return_value = "micro_market"
    object.__setattr__(handlers.deps, "machine_kind_lookup", kind_lookup)
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "701"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    callback = callback_query()

    await handlers.on_loading_photos_send_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        "Нужно минимум 2 фотографий.",
        show_alert=True,
    )


def test_loading_photos_handlers_micromarket_insufficient_send() -> None:
    asyncio.run(_test_loading_photos_handlers_micromarket_insufficient_send())


async def _test_loading_photos_photo_received_media_group_stops_at_max() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    for index in range(8):
        append_photo(
            manager,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )

    answer_mock = AsyncMock()
    for extra_index in range(3):
        message = create_autospec(Message, instance=True)
        message.photo = [
            MagicMock(
                file_id=f"file-extra-{extra_index}",
                file_unique_id=f"unique-extra-{extra_index}",
            ),
        ]
        message.message_id = 100 + extra_index
        message.media_group_id = "album-1"
        message.answer = answer_mock

        await handlers.on_loading_photos_photo_received(message, _message_input(), manager)

    assert photo_count(manager) == 10
    answer_mock.assert_awaited_once_with("Максимум 10 фотографий.")


def test_loading_photos_photo_received_media_group_stops_at_max() -> None:
    asyncio.run(_test_loading_photos_photo_received_media_group_stops_at_max())


async def _test_loading_photos_send_rejects_when_over_max() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    for index in range(11):
        append_photo(
            manager,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )
    callback = callback_query()

    with patch(
        "src.interfaces.telegram.machines.handlers_loading_photos.resolve_bot_user",
        new=AsyncMock(return_value=TEST_BOT_USER),
    ):
        await handlers.on_loading_photos_send(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        "Максимум 10 фотографий.",
        show_alert=True,
    )
    handlers.deps.accept_loading_photos.execute.assert_not_called()


def test_loading_photos_send_rejects_when_over_max() -> None:
    asyncio.run(_test_loading_photos_send_rejects_when_over_max())


async def _test_loading_photos_send_stub_shows_max_alert_when_over_limit() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    for index in range(11):
        append_photo(
            manager,
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )
    callback = callback_query()

    await handlers.on_loading_photos_send_stub(callback, button(), manager)

    callback.answer.assert_awaited_once_with(
        "Максимум 10 фотографий.",
        show_alert=True,
    )


def test_loading_photos_send_stub_shows_max_alert_when_over_limit() -> None:
    asyncio.run(_test_loading_photos_send_stub_shows_max_alert_when_over_limit())


def _manager_with_two_photos() -> MagicMock:
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    append_photo(
        manager,
        file_id="file-2",
        file_unique_id="unique-2",
        message_id=2,
    )
    return manager


async def _test_loading_photos_prev_cycles_index() -> None:
    handlers = make_handlers()
    manager = _manager_with_two_photos()
    assert get_photo_index(manager) == 1
    callback = callback_query()

    await handlers.on_loading_photos_prev(callback, button(), manager)

    callback.answer.assert_awaited_once()
    assert get_photo_index(manager) == 0


def test_loading_photos_prev_cycles_index() -> None:
    asyncio.run(_test_loading_photos_prev_cycles_index())


async def _test_loading_photos_next_cycles_index() -> None:
    handlers = make_handlers()
    manager = _manager_with_two_photos()
    set_photo_index(manager, 0)
    callback = callback_query()

    await handlers.on_loading_photos_next(callback, button(), manager)

    callback.answer.assert_awaited_once()
    assert get_photo_index(manager) == 1


def test_loading_photos_next_cycles_index() -> None:
    asyncio.run(_test_loading_photos_next_cycles_index())


async def _test_loading_photos_prev_next_noop_when_single_photo() -> None:
    handlers = make_handlers()
    manager = MagicMock()
    manager.dialog_data = {"machine_id": "vm-1"}
    init_loading_photos_session(manager)
    append_photo(
        manager,
        file_id="file-1",
        file_unique_id="unique-1",
        message_id=1,
    )
    callback = callback_query()

    await handlers.on_loading_photos_prev(callback, button(), manager)
    await handlers.on_loading_photos_next(callback, button(), manager)

    assert callback.answer.await_count == 2
    assert get_photo_index(manager) == 0


def test_loading_photos_prev_next_noop_when_single_photo() -> None:
    asyncio.run(_test_loading_photos_prev_next_noop_when_single_photo())


async def _test_loading_photos_back_clears_session_and_switches_workspace() -> None:
    handlers = make_handlers()
    manager = _manager_with_two_photos()
    manager.switch_to = AsyncMock()
    callback = callback_query()

    await handlers.on_loading_photos_back(callback, button(), manager)

    callback.answer.assert_awaited_once()
    assert photo_count(manager) == 0
    assert "loading_photos_batch_id" not in manager.dialog_data
    manager.switch_to.assert_awaited_once_with(MachineListState.workspace)


def test_loading_photos_back_clears_session_and_switches_workspace() -> None:
    asyncio.run(_test_loading_photos_back_clears_session_and_switches_workspace())
