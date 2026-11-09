from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.photo_batches.ports import DownloadedPhoto


@beartype
@dataclass(frozen=True, slots=True)
class AiogramTelegramPhotoDownloader:
    bot: Bot

    @beartype
    async def download(self, file_id: str) -> DownloadedPhoto:
        if not file_id:
            raise ValueError("file_id must not be empty")
        try:
            telegram_file = await self.bot.get_file(file_id)
            if telegram_file.file_path is None:
                raise NonRetryableOutboxError(f"Telegram file {file_id!r} has no file_path")
            buffer = BytesIO()
            await self.bot.download_file(telegram_file.file_path, destination=buffer)
            data = buffer.getvalue()
            if not data:
                raise NonRetryableOutboxError(f"Telegram file {file_id!r} is empty")
            content_type = _guess_content_type(telegram_file.file_path)
            return DownloadedPhoto(data=data, content_type=content_type)
        except TelegramForbiddenError as error:
            raise NonRetryableOutboxError(str(error)) from error
        except TelegramBadRequest as error:
            message = str(error).lower()
            if "file" in message and ("not found" in message or "wrong" in message):
                raise NonRetryableOutboxError(str(error)) from error
            raise
        except TelegramAPIError:
            raise


@beartype
def _guess_content_type(file_path: str) -> str:
    lowered = file_path.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".heic"):
        return "image/heic"
    return "image/jpeg"
