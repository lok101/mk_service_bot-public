from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pymongo.database import Database
from tests.integration.stack import build_webhook_pipeline_stack

from src.application.outbox.handler_ids import (
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
)
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_batch import PhotoRef
from src.infrastructure.outbox.serialization import event_to_outbox_document

pytestmark = pytest.mark.integration

_SUBMITTED_AT = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def _enqueue_all_handlers(
    stack: object,
    *,
    event: PhotosSubmitted,
) -> None:
    from tests.integration.stack import WebhookPipelineStack

    assert isinstance(stack, WebhookPipelineStack)
    event_document = event_to_outbox_document(event)
    event_id = event.event_id.value
    for handler_id in (
        LOADING_PHOTOS_HANDLER_ID,
        LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    ):
        stack.outbox_store.enqueue(
            event_id=event_id,
            handler_id=handler_id,
            event_document=event_document,
        )


def test_loading_photos_outbox_entry_reaches_processed(mongo_database: Database) -> None:
    stack = build_webhook_pipeline_stack(mongo_database)
    batch_id = BatchId("batch-integration-1")
    event_id = EventId("event-integration-1")

    stack.photo_batch_store.save_pending(
        batch_id=batch_id,
        purpose="loading",
        technician_id=TechnicianId("tech-integration"),
        machine_id=MachineId("vm-integration"),
        submitted_at=_SUBMITTED_AT,
        photos=(
            PhotoRef(
                file_id="file-1",
                file_unique_id="unique-1",
                message_id=1,
            ),
        ),
    )
    stack.photo_batch_store.mark_accepted(
        batch_id,
        event_id=event_id.value,
        occurred_at=_SUBMITTED_AT,
    )

    event = PhotosSubmitted(
        event_id=event_id,
        batch_id=batch_id,
        technician_id=TechnicianId("tech-integration"),
        machine_id=MachineId("vm-integration"),
        photo_count=1,
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )
    _enqueue_all_handlers(stack, event=event)

    async def _drain() -> None:
        for _ in range(10):
            processed = await stack.outbox_worker.process_batch()
            if processed == 0:
                break

    asyncio.run(_drain())

    snapshot = stack.photo_batch_store.get_by_batch_id(batch_id)
    assert snapshot is not None
    assert len(snapshot.stored_files) == 1
    assert snapshot.stored_files[0].content_hash
    assert snapshot.proxy_message_ids == (501,)
