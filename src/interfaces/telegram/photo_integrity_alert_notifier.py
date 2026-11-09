from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile, InputMediaPhoto
from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.photo_batches.ports import PhotoStorage
from src.application.photo_integrity.ports import PhotoIntegrityAlertNotifier
from src.domain.photo_integrity import PhotoIntegrityFinding


@beartype
@dataclass(frozen=True, slots=True)
class NoOpPhotoIntegrityAlertNotifier(PhotoIntegrityAlertNotifier):
    @beartype
    async def notify_duplicate_suspected(
        self,
        *,
        finding: PhotoIntegrityFinding,
        new_photo_file_id: str,
        matched_photo_file_id: str | None,
        matched_storage_key: str,
        new_calendar_day_label: str,
        matched_calendar_day_label: str,
        new_technician_display_name: str,
        matched_technician_display_name: str,
        new_machine_display_name: str,
        matched_machine_display_name: str,
    ) -> None:
        return


@beartype
@dataclass(frozen=True, slots=True)
class TelegramPhotoIntegrityAlertNotifier(PhotoIntegrityAlertNotifier):
    bot: Bot
    chat_id: int
    photo_storage: PhotoStorage

    @beartype
    async def notify_duplicate_suspected(
        self,
        *,
        finding: PhotoIntegrityFinding,
        new_photo_file_id: str,
        matched_photo_file_id: str | None,
        matched_storage_key: str,
        new_calendar_day_label: str,
        matched_calendar_day_label: str,
        new_technician_display_name: str,
        matched_technician_display_name: str,
        new_machine_display_name: str,
        matched_machine_display_name: str,
    ) -> None:
        caption = (
            "⚠️ Подозрение на дубликат фото\n"
            f"finding: {finding.finding_id.value}\n"
            f"новое: {new_calendar_day_label} · {new_technician_display_name} · "
            f"{new_machine_display_name}\n"
            f"совпало: {matched_calendar_day_label} · {matched_technician_display_name} · "
            f"{matched_machine_display_name}"
        )
        matched_media: str | BufferedInputFile
        if matched_photo_file_id:
            matched_media = matched_photo_file_id
        else:
            photo_bytes = await self.photo_storage.get_bytes(matched_storage_key)
            matched_media = BufferedInputFile(photo_bytes, filename="matched.jpg")

        media: Sequence[InputMediaPhoto] = [
            InputMediaPhoto(media=new_photo_file_id, caption=caption),
            InputMediaPhoto(media=matched_media),
        ]
        try:
            await self.bot.send_media_group(chat_id=self.chat_id, media=list(media))
        except TelegramForbiddenError as error:
            raise NonRetryableOutboxError(str(error)) from error
        except TelegramBadRequest as error:
            message = str(error).lower()
            if "chat not found" in message or "bot was blocked" in message:
                raise NonRetryableOutboxError(str(error)) from error
            raise
