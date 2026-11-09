from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from tests.interfaces._warehouse_webhook_dep_fields import warehouse_webhook_dep_kwargs
from tests.interfaces.webhook_request_helpers import make_recording_to_thread, post_signed_webhook

from src.application.form_submissions.accept import AcceptRevisionFormSubmissionService
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.machine_operations.use_cases import RegisterRevisionFromFormCommand
from src.domain.form_tokens import (
    RevisionFormTokenPayload,
    create_revision_form_token,
    verify_inventory_form_token,
    verify_revision_form_token,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier

_WEBHOOK_SECRET = "webhook-secret"
_REVISION_SECRET = "revision-secret"
_INVENTORY_SECRET = "inventory-secret"
_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS = 300
_REVISION_WEBHOOK = "/webhooks/google-forms/revision-submitted"
_MACHINE_ID = MachineId("vm-revision-sig")
_TECHNICIAN_ID = TechnicianId("tech-revision-sig")
_SUBMITTED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _StubRegisterRevisionFromForm:
    def execute(self, command: RegisterRevisionFromFormCommand) -> RevisionCompleted:
        return RevisionCompleted(
            event_id=EventId("event-revision"),
            revision_id=RevisionId("rev-1"),
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            completed_at=command.submitted_at,
            occurred_at=command.submitted_at,
            source=RevisionSource.GOOGLE_FORM,
            form_id=command.form_id,
            form_token=command.form_token,
        )


@dataclass(frozen=True, slots=True)
class _UnusedAcceptInventory:
    def execute_loading(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("loading webhook must not be called")


def _revision_client() -> TestClient:
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    return TestClient(
        build_google_forms_webhook_app(
            GoogleFormsWebhookDeps(
                accept_revision_form_submission=AcceptRevisionFormSubmissionService(
                    form_submission_store=InMemoryFormSubmissionStore(),
                    register_revision_from_form=_StubRegisterRevisionFromForm(),
                    product_code_resolver=resolver,
                    form_token_field_name="Код заявки.",
                ),
                accept_inventory_form_submission=_UnusedAcceptInventory(),  # type: ignore[arg-type]
                form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
                token_field_name="Код заявки.",
                webhook_secret=_WEBHOOK_SECRET,
                webhook_signature_max_age_seconds=_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
                revision_form_token_secret=_REVISION_SECRET,
                inventory_form_token_secret=_INVENTORY_SECRET,
                verify_revision_form_token=verify_revision_form_token,
                verify_inventory_form_token=verify_inventory_form_token,
                **warehouse_webhook_dep_kwargs(),
            ),
        ),
    )


def _revision_token() -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-revision-sig",
        ),
        _REVISION_SECRET,
    )


def _revision_payload(*, token: str) -> dict[str, object]:
    return {
        "form_id": "form-revision-sig",
        "submitted_at": _SUBMITTED_AT.isoformat(),
        "revision_token": token,
        "answers": [
            {"title": "Код заявки.", "value": token},
            {"title": "Кофе", "value": "1"},
        ],
    }


def test_revision_webhook_runs_accept_in_thread_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(asyncio, "to_thread", make_recording_to_thread(calls))
    token = _revision_token()
    response = post_signed_webhook(
        _revision_client(),
        _REVISION_WEBHOOK,
        payload=_revision_payload(token=token),
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    assert "execute" in calls


def test_revision_webhook_rejects_missing_signature_header() -> None:
    client = _revision_client()
    response = client.post(
        _REVISION_WEBHOOK,
        json={
            "form_id": "f",
            "revision_token": "t",
            "submitted_at": "2026-06-08T10:00:00Z",
            "answers": [{"title": "Код заявки.", "value": "t"}],
        },
    )
    assert response.status_code == 422


def test_revision_webhook_rejects_expired_signature() -> None:
    client = _revision_client()
    payload = {
        "form_id": "f",
        "revision_token": "t",
        "submitted_at": datetime(2026, 6, 8, 10, 0, tzinfo=UTC).isoformat(),
        "answers": [{"title": "Код заявки.", "value": "t"}],
    }
    expired_timestamp = int(time.time()) - 3600
    response = post_signed_webhook(
        client,
        _REVISION_WEBHOOK,
        payload=payload,
        secret=_WEBHOOK_SECRET,
        timestamp=expired_timestamp,
    )
    assert response.status_code == 401
