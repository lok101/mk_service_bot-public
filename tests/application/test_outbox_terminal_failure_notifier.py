from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import patch

from src.application.form_workflow.models import FormWorkflowIntegrationFailed
from src.application.outbox.handler_ids import (
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    REVISION_TELEGRAM_HANDLER_ID,
)
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier
from src.domain.form_submission import FormAnswer
from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted, RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.outbox.event_deserializer import OutboxEventDeserializerAdapter
from src.infrastructure.outbox.serialization import event_to_outbox_document

_MACHINE_ID = MachineId("vm-1")
_TECH_ID = TechnicianId("tech-1")
_EVENT_ID = EventId("evt-1")
_OCCURRED_AT = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)


@dataclass
class _RecordingNotifier:
    messages: list[FormWorkflowIntegrationFailed] = field(default_factory=list)

    async def notify(self, message: FormWorkflowIntegrationFailed) -> None:
        self.messages.append(message)


def _store_with_accepted_revision_snapshot() -> InMemoryFormSubmissionStore:
    store = InMemoryFormSubmissionStore()
    pending = store.save_pending(
        form_token="token-1",
        form_id="form-1",
        purpose="revision",
        technician_id=_TECH_ID,
        machine_id=_MACHINE_ID,
        submitted_at=_OCCURRED_AT,
        answers=(FormAnswer(title="Кофе", value="1"),),
        validated_lines=(),
    )
    store.mark_accepted(
        pending.submission_id,
        event_id=_EVENT_ID.value,
        occurred_at=_OCCURRED_AT,
        revision_id="rev-1",
    )
    return store


def test_failure_notifier_notifies_technician_on_revision_telegram_failure() -> None:
    event = RevisionCompleted(
        event_id=_EVENT_ID,
        revision_id=RevisionId("rev-1"),
        technician_id=_TECH_ID,
        machine_id=_MACHINE_ID,
        completed_at=_OCCURRED_AT,
        occurred_at=_OCCURRED_AT,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )
    doc = event_to_outbox_document(event)
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=_store_with_accepted_revision_snapshot(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    asyncio.run(
        service.notify_terminal_failure(
            handler_id=REVISION_TELEGRAM_HANDLER_ID,
            event_document=doc,
            error_message="MoySklad timeout",
        ),
    )
    assert len(notifier.messages) == 1
    assert notifier.messages[0].technician_id == _TECH_ID
    assert "MoySklad timeout" in notifier.messages[0].detail


_PHOTOS_EVENT = PhotosSubmitted(
    event_id=_EVENT_ID,
    batch_id=BatchId("batch-1"),
    technician_id=_TECH_ID,
    machine_id=_MACHINE_ID,
    photo_count=2,
    submitted_at=_OCCURRED_AT,
    occurred_at=_OCCURRED_AT,
)


def test_failure_notifier_logs_ops_alert_for_loading_photos_handler() -> None:
    doc = event_to_outbox_document(_PHOTOS_EVENT)
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    with patch("src.application.outbox.terminal_failure_notifier.logger") as log:
        asyncio.run(
            service.notify_terminal_failure(
                handler_id=LOADING_PHOTOS_HANDLER_ID,
                event_document=doc,
                error_message="S3 upload failed",
            ),
        )
    assert notifier.messages == []
    log.error.assert_called_once()
    log_args = log.error.call_args[0]
    assert LOADING_PHOTOS_HANDLER_ID in log_args
    assert "S3 upload failed" in log_args
    assert "batch-1" in log_args


def test_failure_notifier_logs_ops_alert_for_integrity_handler() -> None:
    doc = event_to_outbox_document(_PHOTOS_EVENT)
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    with patch("src.application.outbox.terminal_failure_notifier.logger") as log:
        asyncio.run(
            service.notify_terminal_failure(
                handler_id=LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
                event_document=doc,
                error_message="hash index error",
            ),
        )
    assert notifier.messages == []
    log.error.assert_called_once()
    log_args = log.error.call_args[0]
    assert LOADING_PHOTOS_INTEGRITY_HANDLER_ID in log_args
    assert "hash index error" in log_args
    assert "batch-1" in log_args


def test_failure_notifier_logs_ops_alert_for_telegram_handler() -> None:
    doc = event_to_outbox_document(_PHOTOS_EVENT)
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    with patch("src.application.outbox.terminal_failure_notifier.logger") as log:
        asyncio.run(
            service.notify_terminal_failure(
                handler_id=LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
                event_document=doc,
                error_message="telegram send failed",
            ),
        )
    assert notifier.messages == []
    log.error.assert_called_once()
    assert (
        log.error.call_args.kwargs["extra"]["outbox_handler_id"]
        == LOADING_PHOTOS_TELEGRAM_HANDLER_ID
    )


def test_failure_notifier_photo_alert_includes_entry_and_claim_extra() -> None:
    doc = event_to_outbox_document(_PHOTOS_EVENT)
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    with patch("src.application.outbox.terminal_failure_notifier.logger") as log:
        asyncio.run(
            service.notify_terminal_failure(
                handler_id=LOADING_PHOTOS_HANDLER_ID,
                event_document=doc,
                error_message="S3 upload failed",
                entry_id="entry-42",
                claim_id="claim-99",
            ),
        )
    extra = log.error.call_args.kwargs["extra"]
    assert extra["outbox_entry_id"] == "entry-42"
    assert extra["outbox_claim_id"] == "claim-99"
    assert extra["outbox_handler_id"] == LOADING_PHOTOS_HANDLER_ID
    assert extra["outbox_event_id"] == _EVENT_ID.value


def test_failure_notifier_logs_form_handler_deserialization_failure() -> None:
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    with patch("src.application.outbox.terminal_failure_notifier.logger") as log:
        asyncio.run(
            service.notify_terminal_failure(
                handler_id=REVISION_TELEGRAM_HANDLER_ID,
                event_document={"invalid": "document"},
                error_message="MoySklad timeout",
                entry_id="entry-1",
                claim_id="claim-1",
            ),
        )
    assert notifier.messages == []
    log.error.assert_called_once()
    message = log.error.call_args[0][0]
    assert "could not deserialize event" in message
    extra = log.error.call_args.kwargs["extra"]
    assert extra["outbox_entry_id"] == "entry-1"
    assert extra["outbox_claim_id"] == "claim-1"


def test_failure_notifier_logs_when_photo_event_deserialization_fails() -> None:
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    with patch("src.application.outbox.terminal_failure_notifier.logger") as log:
        asyncio.run(
            service.notify_terminal_failure(
                handler_id=LOADING_PHOTOS_HANDLER_ID,
                event_document={"invalid": "document"},
                error_message="S3 upload failed",
            ),
        )
    assert notifier.messages == []
    log.error.assert_called_once()
    message = log.error.call_args[0][0]
    assert "could not deserialize event" in message


def test_failure_notifier_ignores_unknown_handler() -> None:
    notifier = _RecordingNotifier()
    service = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=notifier,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    asyncio.run(
        service.notify_terminal_failure(
            handler_id="unknown-handler",
            event_document={},
            error_message="err",
        ),
    )
    assert notifier.messages == []
