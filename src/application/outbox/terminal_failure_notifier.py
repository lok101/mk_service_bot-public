from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.form_submissions.ports import FormSubmissionStore
from src.application.form_workflow import FormWorkflowIntegrationFailed, FormWorkflowNotifier
from src.application.outbox.handler_ids import (
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    LOADING_TELEGRAM_HANDLER_ID,
    REVISION_TELEGRAM_HANDLER_ID,
)
from src.application.outbox.logging import outbox_log_extra
from src.application.outbox.ports import OutboxEventDeserializer
from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    PhotosSubmitted,
    RevisionCompleted,
)

logger = logging.getLogger(__name__)

_PHOTO_OUTBOX_HANDLER_IDS = frozenset(
    {
        LOADING_PHOTOS_HANDLER_ID,
        LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    },
)

_HANDLER_PURPOSE: dict[str, FormSubmissionPurpose] = {
    REVISION_TELEGRAM_HANDLER_ID: "revision",
    LOADING_TELEGRAM_HANDLER_ID: "loading",
}


@beartype
@dataclass(frozen=True, slots=True)
class OutboxTerminalFailureNotifier:
    form_submission_store: FormSubmissionStore
    form_workflow_notifier: FormWorkflowNotifier
    event_deserializer: OutboxEventDeserializer

    @beartype
    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        log_extra = outbox_log_extra(
            entry_id=entry_id,
            handler_id=handler_id,
            claim_id=claim_id,
        )
        purpose = _HANDLER_PURPOSE.get(handler_id)
        if handler_id in _PHOTO_OUTBOX_HANDLER_IDS:
            try:
                event = self.event_deserializer.from_document(event_document)
            except Exception:
                logger.error(
                    "Outbox terminal failure handler=%s: could not deserialize event: %s",
                    handler_id,
                    error_message,
                    extra=log_extra,
                )
                return
            if not isinstance(event, PhotosSubmitted):
                logger.error(
                    "Outbox terminal failure handler=%s: unexpected event type %s: %s",
                    handler_id,
                    type(event).__name__,
                    error_message,
                    extra=log_extra,
                )
                return
            logger.error(
                "Outbox terminal failure handler=%s event_id=%s batch_id=%s "
                "technician_id=%s machine_id=%s: %s",
                handler_id,
                event.event_id.value,
                event.batch_id.value,
                event.technician_id.value,
                event.machine_id.value,
                error_message,
                extra=outbox_log_extra(
                    entry_id=entry_id,
                    handler_id=handler_id,
                    event_id=event.event_id.value,
                    claim_id=claim_id,
                ),
            )
            return

        if purpose is None:
            return

        try:
            event = self.event_deserializer.from_document(event_document)
        except Exception:
            logger.error(
                "Outbox terminal failure handler=%s: could not deserialize event: %s",
                handler_id,
                error_message,
                extra=log_extra,
            )
            return

        technician_id: TechnicianId | None
        machine_id: MachineId | None
        if isinstance(event, (RevisionCompleted, LoadingSubmitted)):
            technician_id = event.technician_id
            machine_id = event.machine_id
        else:
            return

        if handler_id == REVISION_TELEGRAM_HANDLER_ID:
            await self.form_workflow_notifier.notify(
                FormWorkflowIntegrationFailed(
                    technician_id=technician_id,
                    machine_id=machine_id,
                    purpose=purpose,
                    detail=f"Не удалось открыть экран обслуживания: {error_message}",
                ),
            )
            return

        snapshot = self.form_submission_store.get_by_event_id(event.event_id.value)
        if snapshot is None and handler_id not in {
            LOADING_TELEGRAM_HANDLER_ID,
        }:
            return

        await self.form_workflow_notifier.notify(
            FormWorkflowIntegrationFailed(
                technician_id=technician_id,
                machine_id=machine_id,
                purpose=purpose,
                detail=error_message,
            ),
        )
