from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pymongo.database import Database
from tests.integration.stack import (
    INVENTORY_FORM_TOKEN_SECRET,
    WEBHOOK_SECRET,
    build_webhook_pipeline_stack,
    inventory_form_answers,
)
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.outbox.handler_ids import TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    create_loading_form_token,
)
from src.domain.form_tokens.codec import _create_machine_form_token
from src.domain.ids import MachineId
from src.domain.machine_operations.events import LoadingSubmitted
from src.infrastructure.outbox.memory import OUTBOX_STATUS_PROCESSED
from src.infrastructure.testing import (
    TEST_TECHNICIAN_ID,
    seed_test_machine_revision_events,
)

pytestmark = pytest.mark.integration

_LOADING_WEBHOOK = "/webhooks/google-forms/loading-submitted"
_MACHINE_ID = MachineId("vm-01")


def _loading_token(*, nonce: str) -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce=nonce,
        ),
        INVENTORY_FORM_TOKEN_SECRET,
    )


def test_loading_webhook_persists_event_and_accepts_form_submission(
    mongo_database: Database,
) -> None:
    stack = build_webhook_pipeline_stack(mongo_database)
    seed_test_machine_revision_events(stack.event_store)
    loading_token = _loading_token(nonce="nonce-loading-e2e")
    submitted_at = "2026-05-20T11:00:00Z"

    response = post_signed_webhook(
        stack.webhook_client,
        _LOADING_WEBHOOK,
        payload={
            "form_id": "form-loading-integration",
            "submitted_at": submitted_at,
            "token": loading_token,
            "answers": inventory_form_answers(loading_token),
        },
        secret=WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    body = response.json()
    event_id = body["event_id"]
    assert body["status"] == "accepted"
    assert body["purpose"] == "loading"
    assert body["machine_id"] == _MACHINE_ID.value
    assert body["technician_id"] == TEST_TECHNICIAN_ID.value

    stored_events = stack.event_store.get_events_for_machine(_MACHINE_ID)
    loading_events = [event for event in stored_events if isinstance(event, LoadingSubmitted)]
    assert len(loading_events) == 1
    assert loading_events[0].event_id.value == event_id
    assert loading_events[0].form_token == loading_token

    snapshot = stack.form_submission_store.get_by_event_id(event_id)
    assert snapshot is not None
    assert snapshot.status == "accepted"
    assert snapshot.purpose == "loading"

    assert (
        mongo_database["domain_event_outbox"].find_one(
            {"event_id": event_id, "handler_id": "loading_move"},
        )
        is None
    )

    outbox_entry = mongo_database["domain_event_outbox"].find_one(
        {
            "event_id": event_id,
            "handler_id": TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
        },
    )
    assert outbox_entry is not None
    assert outbox_entry["status"] == "pending"

    processed_count = asyncio.run(stack.outbox_worker.process_batch())
    assert processed_count == 1

    outbox_entry = mongo_database["domain_event_outbox"].find_one(
        {"event_id": event_id, "handler_id": TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID},
    )
    assert outbox_entry is not None
    assert outbox_entry["status"] == OUTBOX_STATUS_PROCESSED


def test_loading_webhook_accepts_submission_in_handover_phase(
    mongo_database: Database,
) -> None:
    stack = build_webhook_pipeline_stack(mongo_database)
    seed_test_machine_revision_events(stack.event_store)
    machine_id = MachineId("vm-02")
    loading_token = create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=TEST_TECHNICIAN_ID,
            machine_id=machine_id,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-loading-handover-e2e",
        ),
        INVENTORY_FORM_TOKEN_SECRET,
    )
    submitted_at = "2026-05-20T11:00:00Z"

    response = post_signed_webhook(
        stack.webhook_client,
        _LOADING_WEBHOOK,
        payload={
            "form_id": "form-loading-handover",
            "submitted_at": submitted_at,
            "token": loading_token,
            "answers": inventory_form_answers(loading_token),
        },
        secret=WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    stored_events = stack.event_store.get_events_for_machine(machine_id)
    loading_events = [event for event in stored_events if isinstance(event, LoadingSubmitted)]
    assert len(loading_events) == 1
    assert loading_events[0].technician_id == TEST_TECHNICIAN_ID


_PRELOAD_MACHINE_ID = MachineId("vm-preload-e2e")


def _pre_loading_token(*, nonce: str) -> str:
    return _create_machine_form_token(
        technician_id=TEST_TECHNICIAN_ID,
        machine_id=_PRELOAD_MACHINE_ID,
        issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
        nonce=nonce,
        purpose="pre_loading",
        secret=INVENTORY_FORM_TOKEN_SECRET,
    )


def test_pre_loading_webhook_returns_422(
    mongo_database: Database,
) -> None:
    stack = build_webhook_pipeline_stack(mongo_database)
    pre_loading_token = _pre_loading_token(nonce="nonce-preloading-e2e")
    submitted_at = "2026-05-20T10:30:00Z"

    response = post_signed_webhook(
        stack.webhook_client,
        _LOADING_WEBHOOK,
        payload={
            "form_id": "form-preloading-integration",
            "submitted_at": submitted_at,
            "token": pre_loading_token,
            "answers": inventory_form_answers(pre_loading_token),
        },
        secret=WEBHOOK_SECRET,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert detail

    stored_events = stack.event_store.get_events_for_machine(_PRELOAD_MACHINE_ID)
    assert stored_events == []
