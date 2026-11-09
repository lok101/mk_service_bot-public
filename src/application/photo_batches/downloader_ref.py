from __future__ import annotations

from dataclasses import dataclass

from src.application.photo_batches.ports import TelegramPhotoDownloader


@dataclass(slots=True)
class PhotoDownloaderRef:
    """Mutable holder so outbox can use a real downloader after Telegram bot starts."""

    downloader: TelegramPhotoDownloader
