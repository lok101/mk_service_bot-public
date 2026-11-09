from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from pymongo import MongoClient
from tests.e2e.http_helpers import post_signed_webhook_http

from src.domain.form_tokens import RevisionFormTokenPayload, create_revision_form_token
from src.domain.ids import MachineId, TechnicianId

pytestmark = pytest.mark.docker_e2e

_WEBHOOK_SECRET = "e2e-webhook-secret"
_TOKEN_SECRET = "e2e-revision-form-token-secret"
_TOKEN_FIELD = "Код заявки."


def test_revision_webhook_docker_e2e_persists_and_processes_outbox(
    e2e_stack: dict[str, str],
) -> None:
    machine_id = MachineId("vm-docker-e2e")
    technician_id = TechnicianId("tech-docker-e2e")
    token = create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=technician_id,
            machine_id=machine_id,
            issued_at=datetime(2026, 7, 28, 9, 0, tzinfo=UTC),
            nonce="nonce-docker-e2e-revision",
        ),
        _TOKEN_SECRET,
    )
    status, raw = post_signed_webhook_http(
        e2e_stack["api"],
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": "form-docker-e2e",
            "submitted_at": "2026-07-28T10:00:00Z",
            "revision_token": token,
            "answers": [{"title": _TOKEN_FIELD, "value": token}],
        },
        secret=_WEBHOOK_SECRET,
    )
    assert status == 200
    body = json.loads(raw.decode("utf-8"))
    event_id = body["event_id"]

    client = MongoClient(e2e_stack["mongo_uri"])
    db = client["mk_service_bot_e2e"]
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            events = list(
                db["machine_events"].find({"aggregate_id": machine_id.value}),
            )
            outbox = list(db["domain_event_outbox"].find({"event_id": event_id}))
            if events and outbox and all(doc.get("status") == "processed" for doc in outbox):
                break
            time.sleep(1)
        else:
            pytest.fail(
                f"timeout waiting processed outbox; events={events!r} outbox={outbox!r}",
            )
        assert any(doc.get("event_id") == event_id for doc in events)
        submissions = list(db["form_submissions"].find({"event_id": event_id}))
        assert submissions
    finally:
        client.close()


def test_revision_webhook_docker_e2e_rejects_bad_signature(e2e_stack: dict[str, str]) -> None:
    status, _raw = post_signed_webhook_http(
        e2e_stack["api"],
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": "form-docker-e2e",
            "submitted_at": "2026-07-28T10:00:00Z",
            "revision_token": "not-a-token",
            "answers": [],
        },
        secret="wrong-secret",
    )
    assert status in {401, 403}
