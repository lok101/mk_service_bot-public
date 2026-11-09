from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiogram import Bot
from pydantic import SecretStr
from tests.infrastructure.composition_helpers import build_minimal_container

from src.application.outbox.handler_ids import LOADING_PHOTOS_TELEGRAM_HANDLER_ID
from src.config.telegram import TelegramSettings
from src.domain.machine_operations.events import PhotosSubmitted
from src.infrastructure.photo_batches.telegram_downloader import AiogramTelegramPhotoDownloader
from src.interfaces.telegram.loading_photos_notifier import (
    KindRoutedLoadingPhotosChatNotifier,
    NoOpLoadingPhotosChatNotifier,
)


def _telegram_settings(**overrides: object) -> TelegramSettings:
    defaults = {
        "bot_token": SecretStr("dev-bot-token-16chars"),
        "webhook_public_host": "",
    }
    defaults.update(overrides)
    return TelegramSettings.model_construct(**defaults)


def _test_bot() -> Bot:
    return Bot(token="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef")


def _patch_settings(
    monkeypatch: pytest.MonkeyPatch,
    telegram_settings: TelegramSettings,
) -> None:
    settings = MagicMock()
    settings.telegram = telegram_settings
    settings.service_calendar.service_day_end_hour = 6
    monkeypatch.setattr(
        "src.infrastructure.composition.runtime_telegram.get_settings",
        lambda: settings,
    )


def test_register_upgrades_downloader_without_telegram_when_no_chat_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, _telegram_settings())
    container = build_minimal_container()
    bot = _test_bot()

    container.register_telegram_loading_photos(bot)

    assert isinstance(container.photos.downloader_ref.downloader, AiogramTelegramPhotoDownloader)
    assert container.loading_photos_telegram_registered is False
    assert not container.outbox.processors.is_registered(LOADING_PHOTOS_TELEGRAM_HANDLER_ID)
    assert (
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID
        not in container.outbox.publisher._handler_ids_by_event_type.get(
            PhotosSubmitted,
            [],
        )
    )
    assert isinstance(
        container.photos.loading_photos_notifier_ref.notifier,
        NoOpLoadingPhotosChatNotifier,
    )


def test_register_telegram_handler_when_chat_id_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        _telegram_settings(loading_photos_chat_id=-100123456),
    )
    container = build_minimal_container()
    bot = _test_bot()

    container.register_telegram_loading_photos(bot)

    assert container.loading_photos_telegram_registered is True
    assert not container.outbox.processors.is_registered(LOADING_PHOTOS_TELEGRAM_HANDLER_ID)
    assert (
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID
        in container.outbox.publisher._handler_ids_by_event_type.get(
            PhotosSubmitted,
            [],
        )
    )
    effects = build_minimal_container()
    effects.register_telegram_loading_photos(bot, process="effects")
    assert effects.outbox.processors.is_registered(LOADING_PHOTOS_TELEGRAM_HANDLER_ID)
    assert (
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID
        not in effects.outbox.publisher._handler_ids_by_event_type.get(
            PhotosSubmitted,
            [],
        )
    )
    assert isinstance(
        container.photos.loading_photos_notifier_ref.notifier,
        KindRoutedLoadingPhotosChatNotifier,
    )
    routed = container.photos.loading_photos_notifier_ref.notifier
    assert routed.coffee_chat_id == -100123456
    assert routed.micromarket_chat_id is None


def test_register_twice_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        _telegram_settings(loading_photos_chat_id=-100123456),
    )
    container = build_minimal_container()
    bot = _test_bot()

    container.register_telegram_loading_photos(bot)
    container.register_telegram_loading_photos(bot)

    handler_ids = container.outbox.publisher._handler_ids_by_event_type.get(PhotosSubmitted, [])
    assert handler_ids.count(LOADING_PHOTOS_TELEGRAM_HANDLER_ID) == 1
    assert container.loading_photos_telegram_registered is True
