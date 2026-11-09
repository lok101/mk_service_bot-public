from __future__ import annotations

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from src.application.form_submissions import NonRetryableOutboxError
from src.infrastructure.photo_batches.telegram_downloader import (
    AiogramTelegramPhotoDownloader,
    _guess_content_type,
)


def _downloader(*, bot: Bot | None = None) -> AiogramTelegramPhotoDownloader:
    return AiogramTelegramPhotoDownloader(bot=bot or create_autospec(Bot, instance=True))


def test_download_empty_file_id_raises_value_error() -> None:
    downloader = _downloader()

    with pytest.raises(ValueError, match="file_id must not be empty"):
        asyncio.run(downloader.download(""))


async def _test_download_png_returns_content_type() -> None:
    bot = create_autospec(Bot, instance=True)
    telegram_file = MagicMock()
    telegram_file.file_path = "photos/x.png"
    bot.get_file = AsyncMock(return_value=telegram_file)

    async def _write_file(_path: str, *, destination: BytesIO) -> None:
        destination.write(b"\x89PNG\r\n\x1a\n")

    bot.download_file = AsyncMock(side_effect=_write_file)
    downloader = _downloader(bot=bot)

    result = await downloader.download("file-1")

    assert result.data == b"\x89PNG\r\n\x1a\n"
    assert result.content_type == "image/png"


def test_download_png_returns_content_type() -> None:
    asyncio.run(_test_download_png_returns_content_type())


async def _test_download_missing_file_path_raises_non_retryable() -> None:
    bot = create_autospec(Bot, instance=True)
    telegram_file = MagicMock()
    telegram_file.file_path = None
    bot.get_file = AsyncMock(return_value=telegram_file)
    downloader = _downloader(bot=bot)

    with pytest.raises(NonRetryableOutboxError, match="no file_path"):
        await downloader.download("file-1")


def test_download_missing_file_path_raises_non_retryable() -> None:
    asyncio.run(_test_download_missing_file_path_raises_non_retryable())


async def _test_download_empty_bytes_raises_non_retryable() -> None:
    bot = create_autospec(Bot, instance=True)
    telegram_file = MagicMock()
    telegram_file.file_path = "photos/x.jpg"
    bot.get_file = AsyncMock(return_value=telegram_file)
    bot.download_file = AsyncMock(return_value=None)
    downloader = _downloader(bot=bot)

    with pytest.raises(NonRetryableOutboxError, match="is empty"):
        await downloader.download("file-1")


def test_download_empty_bytes_raises_non_retryable() -> None:
    asyncio.run(_test_download_empty_bytes_raises_non_retryable())


async def _test_download_forbidden_maps_to_non_retryable() -> None:
    bot = create_autospec(Bot, instance=True)
    bot.get_file = AsyncMock(side_effect=TelegramForbiddenError(method=None, message="forbidden"))
    downloader = _downloader(bot=bot)

    with pytest.raises(NonRetryableOutboxError):
        await downloader.download("file-1")


def test_download_forbidden_maps_to_non_retryable() -> None:
    asyncio.run(_test_download_forbidden_maps_to_non_retryable())


async def _test_download_bad_request_file_not_found_maps_to_non_retryable() -> None:
    bot = create_autospec(Bot, instance=True)
    bot.get_file = AsyncMock(
        side_effect=TelegramBadRequest(method=None, message="file not found"),
    )
    downloader = _downloader(bot=bot)

    with pytest.raises(NonRetryableOutboxError):
        await downloader.download("file-1")


def test_download_bad_request_file_not_found_maps_to_non_retryable() -> None:
    asyncio.run(_test_download_bad_request_file_not_found_maps_to_non_retryable())


async def _test_download_bad_request_other_reraises() -> None:
    bot = create_autospec(Bot, instance=True)
    bot.get_file = AsyncMock(
        side_effect=TelegramBadRequest(method=None, message="invalid query"),
    )
    downloader = _downloader(bot=bot)

    with pytest.raises(TelegramBadRequest):
        await downloader.download("file-1")


def test_download_bad_request_other_reraises() -> None:
    asyncio.run(_test_download_bad_request_other_reraises())


async def _test_download_api_error_reraises() -> None:
    bot = create_autospec(Bot, instance=True)
    bot.get_file = AsyncMock(side_effect=TelegramAPIError(method=None, message="timeout"))
    downloader = _downloader(bot=bot)

    with pytest.raises(TelegramAPIError):
        await downloader.download("file-1")


def test_download_api_error_reraises() -> None:
    asyncio.run(_test_download_api_error_reraises())


@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        ("photos/x.png", "image/png"),
        ("photos/x.webp", "image/webp"),
        ("photos/x.heic", "image/heic"),
        ("photos/x.jpg", "image/jpeg"),
    ],
)
def test_guess_content_type(file_path: str, expected: str) -> None:
    assert _guess_content_type(file_path) == expected
