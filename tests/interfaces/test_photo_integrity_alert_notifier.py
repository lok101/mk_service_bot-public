from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from src.application.form_submissions.outbox_errors import NonRetryableOutboxError
from src.domain.ids import BatchId, FindingId, TechnicianId
from src.domain.photo_integrity import PhotoIntegrityFinding
from src.infrastructure.photo_batches.stubs import InMemoryPhotoStorage
from src.interfaces.telegram.photo_integrity_alert_notifier import (
    TelegramPhotoIntegrityAlertNotifier,
)

_FINDING = PhotoIntegrityFinding(
    finding_id=FindingId("finding-1"),
    status="pending_review",
    new_batch_id=BatchId("batch-new"),
    matched_batch_id=BatchId("batch-old"),
    technician_id=TechnicianId("tech-1"),
    content_hash="a" * 64,
    photo_index=0,
    detected_at=datetime(2026, 6, 5, tzinfo=UTC),
)


def test_integrity_alert_notifier_raises_non_retryable_on_chat_not_found() -> None:
    bot = MagicMock()
    bot.send_media_group = AsyncMock(
        side_effect=TelegramBadRequest(
            method="sendMediaGroup", message="Bad Request: chat not found"
        ),
    )
    notifier = TelegramPhotoIntegrityAlertNotifier.__new__(TelegramPhotoIntegrityAlertNotifier)
    object.__setattr__(notifier, "bot", bot)
    object.__setattr__(notifier, "chat_id", -100123)
    object.__setattr__(notifier, "photo_storage", InMemoryPhotoStorage())

    with pytest.raises(NonRetryableOutboxError):
        asyncio.run(
            notifier.notify_duplicate_suspected(
                finding=_FINDING,
                new_photo_file_id="file-new",
                matched_photo_file_id="file-old",
                matched_storage_key="memory://x",
                new_calendar_day_label="05.06.2026",
                matched_calendar_day_label="04.06.2026",
                new_technician_display_name="Иванов",
                matched_technician_display_name="Петров",
                new_machine_display_name="vm-1",
                matched_machine_display_name="vm-2",
            ),
        )
