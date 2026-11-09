from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pymongo.database import Database
from tests.integration.stack import (
    FORM_TOKEN_SECRET,
    WEBHOOK_SECRET,
    build_revision_pipeline_stack,
    default_form_answers,
)
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.outbox.handler_ids import (
    PERIOD_RECONCILIATION_HANDLER_ID,
)
from src.domain.form_tokens import RevisionFormTokenPayload, create_revision_form_token
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.infrastructure.outbox.memory import OUTBOX_STATUS_PROCESSED

pytestmark = pytest.mark.integration


def _revision_token(
    *,
    machine_id: MachineId,
    technician_id: TechnicianId,
    nonce: str,
) -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=technician_id,
            machine_id=machine_id,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce=nonce,
        ),
        FORM_TOKEN_SECRET,
    )


def test_revision_webhook_persists_event_enqueues_outbox_and_registers_inventory(
    mongo_database: Database,
) -> None:
    """Webhook revision → event store, inventory + period reconciliation outbox.

    Also registers MoySklad inventory.
    """
    machine_id = MachineId("vm-integration-e2e")
    technician_id = TechnicianId("tech-integration")
    revision_token = _revision_token(
        machine_id=machine_id,
        technician_id=technician_id,
        nonce="nonce-e2e",
    )
    stack = build_revision_pipeline_stack(mongo_database)
    submitted_at = "2026-05-20T10:00:00Z"

    response = post_signed_webhook(
        stack.webhook_client,
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": "form-integration",
            "submitted_at": submitted_at,
            "revision_token": revision_token,
            "answers": default_form_answers(revision_token),
        },
        secret=WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    body = response.json()
    event_id = body["event_id"]
    assert body["status"] == "accepted"
    assert body["machine_id"] == machine_id.value
    assert body["technician_id"] == technician_id.value

    stored_events = stack.event_store.get_events_for_machine(machine_id)
    assert len(stored_events) == 1
    stored_event = stored_events[0]
    assert isinstance(stored_event, RevisionCompleted)
    assert stored_event.event_id.value == event_id
    assert stored_event.form_token == revision_token

    outbox_entry = mongo_database["domain_event_outbox"].find_one(
        {
            "event_id": event_id,
            "handler_id": "revision_inventory",
        },
    )
    assert outbox_entry is None

    pending_outbox = mongo_database["domain_event_outbox"].count_documents(
        {"event_id": event_id, "status": "pending"},
    )
    assert pending_outbox == 1

    processed_count = asyncio.run(stack.outbox_worker.process_batch())
    assert processed_count == pending_outbox

    reconciliation_outbox = mongo_database["domain_event_outbox"].find_one(
        {"event_id": event_id, "handler_id": PERIOD_RECONCILIATION_HANDLER_ID},
    )
    assert reconciliation_outbox is not None
    assert reconciliation_outbox["status"] == OUTBOX_STATUS_PROCESSED

    snapshot = stack.form_submission_store.get_by_event_id(event_id)
    assert snapshot is not None
    assert snapshot.status == "accepted"
