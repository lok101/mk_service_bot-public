from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.application.master_data import MachineKind
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef
from src.interfaces.telegram.loading_photos_notifier import (
    KindRoutedLoadingPhotosChatNotifier,
    TelegramLoadingPhotosChatNotifier,
)


def _photo(index: int) -> PhotoRef:
    return PhotoRef(
        file_id=f"file-{index}",
        file_unique_id=f"unique-{index}",
        message_id=index,
    )


def _snapshot(photo_count: int) -> PhotoBatchSnapshot:
    return PhotoBatchSnapshot(
        batch_id=BatchId("batch-chunk"),
        purpose="loading",
        status="accepted",
        technician_id=TechnicianId("tech-1"),
        machine_id=MachineId("vm-1"),
        submitted_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        photos=tuple(_photo(index) for index in range(photo_count)),
        stored_files=(),
        event_id=EventId("event-1").value,
        occurred_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
    )


def _message(message_id: int) -> MagicMock:
    message = MagicMock()
    message.message_id = message_id
    return message


def _notifier(bot: MagicMock) -> TelegramLoadingPhotosChatNotifier:
    notifier = TelegramLoadingPhotosChatNotifier.__new__(TelegramLoadingPhotosChatNotifier)
    object.__setattr__(notifier, "bot", bot)
    object.__setattr__(notifier, "chat_id", -100)
    return notifier


async def _test_notify_batch_sends_single_media_group_for_ten_photos() -> None:
    bot = MagicMock()
    bot.send_media_group = AsyncMock(
        return_value=[_message(message_id) for message_id in range(500, 510)],
    )
    bot.send_photo = AsyncMock()
    notifier = _notifier(bot)

    message_ids = await notifier.notify_batch(
        snapshot=_snapshot(10),
        technician_display_name="Иванов",
        machine_display_name="ТЦ",
        calendar_day_label="10.06.2026",
    )

    bot.send_media_group.assert_awaited_once()
    bot.send_photo.assert_not_awaited()
    assert message_ids == tuple(range(500, 510))


async def _test_notify_batch_chunks_eleven_photos_into_album_and_single() -> None:
    bot = MagicMock()
    bot.send_media_group = AsyncMock(
        return_value=[_message(message_id) for message_id in range(600, 610)],
    )
    bot.send_photo = AsyncMock(return_value=_message(610))
    notifier = _notifier(bot)

    message_ids = await notifier.notify_batch(
        snapshot=_snapshot(11),
        technician_display_name="Иванов",
        machine_display_name="ТЦ",
        calendar_day_label="10.06.2026",
    )

    bot.send_media_group.assert_awaited_once()
    assert len(bot.send_media_group.await_args.kwargs["media"]) == 10
    first_media = bot.send_media_group.await_args.kwargs["media"][0]
    assert first_media.caption is not None
    assert bot.send_media_group.await_args.kwargs["media"][1].caption is None
    bot.send_photo.assert_awaited_once()
    assert bot.send_photo.await_args.kwargs["caption"] is None
    assert message_ids == (*range(600, 610), 610)


async def _test_notify_batch_chunks_twenty_photos_into_two_albums() -> None:
    bot = MagicMock()
    bot.send_media_group = AsyncMock(
        side_effect=[
            [_message(message_id) for message_id in range(700, 710)],
            [_message(message_id) for message_id in range(710, 720)],
        ],
    )
    bot.send_photo = AsyncMock()
    notifier = _notifier(bot)

    message_ids = await notifier.notify_batch(
        snapshot=_snapshot(20),
        technician_display_name="Иванов",
        machine_display_name="ТЦ",
        calendar_day_label="10.06.2026",
    )

    assert bot.send_media_group.await_count == 2
    bot.send_photo.assert_not_awaited()
    assert message_ids == tuple(range(700, 720))


def test_notify_batch_sends_single_media_group_for_ten_photos() -> None:
    asyncio.run(_test_notify_batch_sends_single_media_group_for_ten_photos())


def test_notify_batch_chunks_eleven_photos_into_album_and_single() -> None:
    asyncio.run(_test_notify_batch_chunks_eleven_photos_into_album_and_single())


def test_notify_batch_chunks_twenty_photos_into_two_albums() -> None:
    asyncio.run(_test_notify_batch_chunks_twenty_photos_into_two_albums())


class _StaticKindLookup:
    def __init__(self, kind: MachineKind | None) -> None:
        self._kind = kind

    def kind_of(self, machine_code: str) -> MachineKind | None:
        del machine_code
        return self._kind


def _routed_notifier(
    bot: MagicMock,
    *,
    kind: MachineKind | None,
    coffee_chat_id: int | None,
    micromarket_chat_id: int | None,
) -> KindRoutedLoadingPhotosChatNotifier:
    notifier = KindRoutedLoadingPhotosChatNotifier.__new__(KindRoutedLoadingPhotosChatNotifier)
    object.__setattr__(notifier, "bot", bot)
    object.__setattr__(notifier, "kind_lookup", _StaticKindLookup(kind))
    object.__setattr__(notifier, "coffee_chat_id", coffee_chat_id)
    object.__setattr__(notifier, "micromarket_chat_id", micromarket_chat_id)
    return notifier


async def _test_routed_micromarket_uses_micromarket_chat() -> None:
    # happy: micromarket → micromarket chat
    bot = MagicMock()
    bot.send_photo = AsyncMock(return_value=_message(42))
    bot.send_media_group = AsyncMock()
    notifier = _routed_notifier(
        bot,
        kind=MachineKind.MICRO_MARKET,
        coffee_chat_id=-1001,
        micromarket_chat_id=-2002,
    )
    message_ids = await notifier.notify_batch(
        snapshot=_snapshot(1),
        technician_display_name="Иванов",
        machine_display_name="Холодильник",
        calendar_day_label="10.06.2026",
    )
    assert message_ids == (42,)
    assert bot.send_photo.await_args.kwargs["chat_id"] == -2002


async def _test_routed_micromarket_without_chat_skips_coffee_fallback() -> None:
    # edge: no micromarket chat → no coffee fallback
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_media_group = AsyncMock()
    notifier = _routed_notifier(
        bot,
        kind=MachineKind.MICRO_MARKET,
        coffee_chat_id=-1001,
        micromarket_chat_id=None,
    )
    message_ids = await notifier.notify_batch(
        snapshot=_snapshot(1),
        technician_display_name="Иванов",
        machine_display_name="Холодильник",
        calendar_day_label="10.06.2026",
    )
    assert message_ids == ()
    bot.send_photo.assert_not_awaited()
    bot.send_media_group.assert_not_awaited()


async def _test_routed_coffee_uses_loading_photos_chat() -> None:
    bot = MagicMock()
    bot.send_photo = AsyncMock(return_value=_message(7))
    notifier = _routed_notifier(
        bot,
        kind=MachineKind.COFFEE,
        coffee_chat_id=-1001,
        micromarket_chat_id=-2002,
    )
    message_ids = await notifier.notify_batch(
        snapshot=_snapshot(1),
        technician_display_name="Иванов",
        machine_display_name="Кофе",
        calendar_day_label="10.06.2026",
    )
    assert message_ids == (7,)
    assert bot.send_photo.await_args.kwargs["chat_id"] == -1001


def test_routed_micromarket_uses_micromarket_chat() -> None:
    asyncio.run(_test_routed_micromarket_uses_micromarket_chat())


def test_routed_micromarket_without_chat_skips_coffee_fallback() -> None:
    asyncio.run(_test_routed_micromarket_without_chat_skips_coffee_fallback())


def test_routed_coffee_uses_loading_photos_chat() -> None:
    asyncio.run(_test_routed_coffee_uses_loading_photos_chat())
