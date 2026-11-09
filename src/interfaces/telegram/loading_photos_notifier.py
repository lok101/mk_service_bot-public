from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InputMediaPhoto
from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.master_data import MachineKind
from src.application.micromarket_loading.ports import MachineKindLookup
from src.application.photo_batches import format_loading_photos_caption
from src.application.photo_batches.notifier_ports import LoadingPhotosChatNotifier
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef
from src.domain.telegram_limits import TELEGRAM_MEDIA_GROUP_LIMIT


@beartype
def _photo_chunks(photos: Sequence[PhotoRef]) -> tuple[tuple[PhotoRef, ...], ...]:
    return tuple(
        tuple(photos[index : index + TELEGRAM_MEDIA_GROUP_LIMIT])
        for index in range(0, len(photos), TELEGRAM_MEDIA_GROUP_LIMIT)
    )


async def _notify_batch_to_chat(
    bot: Any,
    chat_id: int,
    *,
    snapshot: PhotoBatchSnapshot,
    technician_display_name: str,
    machine_display_name: str,
    calendar_day_label: str,
) -> tuple[int, ...]:
    """Send photos to a fixed chat. ``bot`` is untyped for test MagicMock + beartype."""
    caption = format_loading_photos_caption(
        calendar_day_label=calendar_day_label,
        technician_display_name=technician_display_name,
        machine_display_name=machine_display_name,
        batch_id=snapshot.batch_id.value,
    )
    message_ids: list[int] = []
    caption_attached = False
    try:
        for chunk in _photo_chunks(snapshot.photos):
            if len(chunk) == 1:
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=chunk[0].file_id,
                    caption=caption if not caption_attached else None,
                )
                message_ids.append(message.message_id)
            else:
                media: Sequence[InputMediaPhoto] = [
                    InputMediaPhoto(
                        media=photo.file_id,
                        caption=caption if not caption_attached and index == 0 else None,
                    )
                    for index, photo in enumerate(chunk)
                ]
                messages = await bot.send_media_group(
                    chat_id=chat_id,
                    media=list(media),
                )
                message_ids.extend(message.message_id for message in messages)
            caption_attached = True
    except TelegramForbiddenError as error:
        raise NonRetryableOutboxError(str(error)) from error
    except TelegramBadRequest as error:
        error_text = str(error).lower()
        if "chat not found" in error_text or "bot was blocked" in error_text:
            raise NonRetryableOutboxError(str(error)) from error
        raise
    return tuple(message_ids)


@beartype
@dataclass(frozen=True, slots=True)
class NoOpLoadingPhotosChatNotifier(LoadingPhotosChatNotifier):
    @beartype
    async def notify_batch(
        self,
        *,
        snapshot: PhotoBatchSnapshot,
        technician_display_name: str,
        machine_display_name: str,
        calendar_day_label: str,
    ) -> tuple[int, ...]:
        return ()


@beartype
@dataclass(frozen=True, slots=True)
class TelegramLoadingPhotosChatNotifier(LoadingPhotosChatNotifier):
    bot: Bot
    chat_id: int

    @beartype
    async def notify_batch(
        self,
        *,
        snapshot: PhotoBatchSnapshot,
        technician_display_name: str,
        machine_display_name: str,
        calendar_day_label: str,
    ) -> tuple[int, ...]:
        return await _notify_batch_to_chat(
            self.bot,
            self.chat_id,
            snapshot=snapshot,
            technician_display_name=technician_display_name,
            machine_display_name=machine_display_name,
            calendar_day_label=calendar_day_label,
        )


@beartype
@dataclass(frozen=True, slots=True)
class KindRoutedLoadingPhotosChatNotifier(LoadingPhotosChatNotifier):
    """Route loading-photo proxy by machine kind (ISS-012).

    ``micro_market`` → ``micromarket_chat_id`` (skip if unset; never coffee chat).
    Other / unknown kinds → ``coffee_chat_id`` (skip if unset).
    """

    bot: Bot
    kind_lookup: MachineKindLookup
    coffee_chat_id: int | None
    micromarket_chat_id: int | None

    @beartype
    async def notify_batch(
        self,
        *,
        snapshot: PhotoBatchSnapshot,
        technician_display_name: str,
        machine_display_name: str,
        calendar_day_label: str,
    ) -> tuple[int, ...]:
        kind = self.kind_lookup.kind_of(snapshot.machine_id.value)
        if kind is MachineKind.MICRO_MARKET:
            chat_id = self.micromarket_chat_id
        else:
            chat_id = self.coffee_chat_id
        if chat_id is None:
            return ()
        return await _notify_batch_to_chat(
            self.bot,
            chat_id,
            snapshot=snapshot,
            technician_display_name=technician_display_name,
            machine_display_name=machine_display_name,
            calendar_day_label=calendar_day_label,
        )
