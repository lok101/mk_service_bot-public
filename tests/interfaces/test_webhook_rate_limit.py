from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype
from fastapi.testclient import TestClient
from tests.interfaces._warehouse_webhook_dep_fields import warehouse_webhook_dep_kwargs
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.form_submissions.accept import AcceptInventoryFormSubmissionService
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.machine_operations.use_cases import RegisterLoadingFromFormCommand
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    create_loading_form_token,
    verify_inventory_form_token,
)
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver
from src.interfaces.google_forms.rate_limit import InMemoryWebhookRateLimiter
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier

_LOADING_SECRET = "loading-secret"
_WEBHOOK_SECRET = "webhook-secret"
_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS = 300
_MACHINE_ID = MachineId("vm-loading")
_TECHNICIAN_ID = TechnicianId("tech-loading")
_SUBMITTED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_LOADING_WEBHOOK = "/webhooks/google-forms/loading-submitted"


@dataclass(frozen=True, slots=True)
class _StubRegisterLoadingFromForm:
    def execute(self, command: RegisterLoadingFromFormCommand) -> LoadingSubmitted:
        return LoadingSubmitted(
            event_id=EventId("event-loading"),
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            submitted_at=command.submitted_at,
            occurred_at=_SUBMITTED_AT,
            form_id=command.form_id,
            form_token=command.form_token,
        )


@dataclass(frozen=True, slots=True)
class _UnusedAcceptRevision:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("revision webhook must not be called")


@beartype
def _loading_token() -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-loading",
        ),
        _LOADING_SECRET,
    )


@beartype
def _loading_payload(*, token: str) -> dict[str, object]:
    return {
        "form_id": "form-loading",
        "submitted_at": _SUBMITTED_AT.isoformat(),
        "token": token,
        "answers": [
            {"title": "Код заявки.", "value": token},
            {"title": "Кофе", "value": "1"},
        ],
    }


@beartype
def _deps() -> GoogleFormsWebhookDeps:
    return GoogleFormsWebhookDeps(
        accept_revision_form_submission=_UnusedAcceptRevision(),  # type: ignore[arg-type]
        accept_inventory_form_submission=AcceptInventoryFormSubmissionService(
            form_submission_store=InMemoryFormSubmissionStore(),
            register_loading_from_form=_StubRegisterLoadingFromForm(),
            product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
            form_token_field_name="Код заявки.",
        ),
        form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
        token_field_name="Код заявки.",
        webhook_secret=_WEBHOOK_SECRET,
        webhook_signature_max_age_seconds=_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
        revision_form_token_secret="revision-secret",
        inventory_form_token_secret=_LOADING_SECRET,
        verify_revision_form_token=lambda token, secret: token,  # type: ignore[return-value]
        verify_inventory_form_token=verify_inventory_form_token,
        **warehouse_webhook_dep_kwargs(),
    )


def test_webhook_rate_limit_returns_429() -> None:
    limiter = InMemoryWebhookRateLimiter(max_requests=2, window_seconds=60.0)
    app = build_google_forms_webhook_app(_deps(), rate_limiter=limiter)
    client = TestClient(app)
    token = _loading_token()
    payload = _loading_payload(token=token)

    for _ in range(2):
        response = post_signed_webhook(
            client,
            _LOADING_WEBHOOK,
            payload=payload,
            secret=_WEBHOOK_SECRET,
        )
        assert response.status_code == 200

    response = post_signed_webhook(
        client,
        _LOADING_WEBHOOK,
        payload=payload,
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 429
    assert response.json() == {"detail": "Too Many Requests"}
    assert response.headers["Retry-After"] == "60"


def test_health_endpoints_not_rate_limited() -> None:
    limiter = InMemoryWebhookRateLimiter(max_requests=1, window_seconds=60.0)
    app = build_google_forms_webhook_app(_deps(), rate_limiter=limiter)
    client = TestClient(app)
    token = _loading_token()
    payload = _loading_payload(token=token)

    assert (
        post_signed_webhook(
            client,
            _LOADING_WEBHOOK,
            payload=payload,
            secret=_WEBHOOK_SECRET,
        ).status_code
        == 200
    )
    assert (
        post_signed_webhook(
            client,
            _LOADING_WEBHOOK,
            payload=payload,
            secret=_WEBHOOK_SECRET,
        ).status_code
        == 429
    )

    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
