from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from beartype import beartype
from fastapi.testclient import TestClient
from tests.interfaces._warehouse_webhook_dep_fields import warehouse_webhook_dep_kwargs
from tests.interfaces.webhook_request_helpers import (
    make_recording_to_thread,
    post_signed_webhook,
    signed_webhook_headers,
)

from src.application.form_submissions.accept import AcceptInventoryFormSubmissionService
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.machine_operations.errors import (
    MACHINE_OPERATIONS_CONCURRENCY_REASON,
    MachineOperationsConcurrencyError,
)
from src.application.machine_operations.use_cases import (
    RegisterLoadingFromForm,
    RegisterLoadingFromFormCommand,
)
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    RevisionFormTokenPayload,
    VerifiedInventoryFormToken,
    build_verify_inventory_form_token,
    create_loading_form_token,
    create_revision_form_token,
    verify_inventory_form_token,
)
from src.domain.form_tokens.codec import _create_machine_form_token
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted
from src.domain.results import LoadingNotAllowed
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver
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
_DEFAULT_ANSWERS = [
    {"title": "Код заявки.", "value": "placeholder"},
    {"title": "Кофе", "value": "1"},
]


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


def _pre_loading_token() -> str:
    return _create_machine_form_token(
        technician_id=_TECHNICIAN_ID,
        machine_id=_MACHINE_ID,
        issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
        nonce="nonce-pre-loading",
        purpose="pre_loading",
        secret=_LOADING_SECRET,
    )


@beartype
def _answers_for_token(token: str) -> list[dict[str, str]]:
    return [
        {"title": "Код заявки.", "value": token},
        {"title": "Кофе", "value": "1"},
    ]


@beartype
def _loading_payload(*, token: str) -> dict[str, object]:
    return {
        "form_id": "form-loading",
        "submitted_at": _SUBMITTED_AT.isoformat(),
        "token": token,
        "answers": _answers_for_token(token),
    }


@beartype
def _client(
    *,
    store: FormSubmissionStore | None = None,
    register_loading: RegisterLoadingFromForm | None = None,
    webhook_max_body_bytes: int = 3_000_000,
    verify_max_age_hours: float | None = None,
) -> TestClient:
    submission_store = store or InMemoryFormSubmissionStore()
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    inventory_token_verifier = (
        build_verify_inventory_form_token(max_age_hours=verify_max_age_hours)
        if verify_max_age_hours is not None
        else verify_inventory_form_token
    )
    return TestClient(
        build_google_forms_webhook_app(
            GoogleFormsWebhookDeps(
                accept_revision_form_submission=_UnusedAcceptRevision(),  # type: ignore[arg-type]
                accept_inventory_form_submission=AcceptInventoryFormSubmissionService(
                    form_submission_store=submission_store,
                    register_loading_from_form=register_loading or _StubRegisterLoadingFromForm(),
                    product_code_resolver=resolver,
                    form_token_field_name="Код заявки.",
                ),
                form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
                token_field_name="Код заявки.",
                webhook_secret=_WEBHOOK_SECRET,
                webhook_signature_max_age_seconds=_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
                revision_form_token_secret="revision-secret",
                inventory_form_token_secret=_LOADING_SECRET,
                verify_revision_form_token=lambda token, secret: token,  # type: ignore[return-value]
                verify_inventory_form_token=inventory_token_verifier,
                webhook_max_body_bytes=webhook_max_body_bytes,
                **warehouse_webhook_dep_kwargs(),
            ),
        ),
    )


@beartype
def _post_loading(
    client: TestClient,
    *,
    payload: dict[str, object],
    secret: str = _WEBHOOK_SECRET,
) -> object:
    return post_signed_webhook(
        client,
        _LOADING_WEBHOOK,
        payload=payload,
        secret=secret,
    )


@dataclass(frozen=True, slots=True)
class _UnusedAcceptRevision:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("revision webhook must not be called")


def test_loading_webhook_runs_accept_in_thread_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(asyncio, "to_thread", make_recording_to_thread(calls))
    token = _loading_token()
    client = _client()
    response = post_signed_webhook(
        client,
        _LOADING_WEBHOOK,
        payload=_loading_payload(token=token),
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 200
    assert "execute_loading" in calls


def test_loading_submitted_dispatches_loading_by_token_purpose() -> None:
    token = _loading_token()
    response = _post_loading(
        _client(),
        payload=_loading_payload(token=token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["purpose"] == "loading"
    assert body["event_id"] == "event-loading"
    assert body["machine_id"] == _MACHINE_ID.value
    assert body["technician_id"] == _TECHNICIAN_ID.value


def test_loading_submitted_rejects_pre_loading_token_purpose() -> None:
    token = _pre_loading_token()
    response = _post_loading(
        _client(),
        payload={
            "form_id": "form-loading",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": token,
            "answers": _answers_for_token(token),
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert detail  # invalid residual purpose → 422 (generic unsupported ok)


@dataclass(frozen=True, slots=True)
class _RejectLoadingRegister:
    def execute(self, command: RegisterLoadingFromFormCommand) -> LoadingNotAllowed:
        return LoadingNotAllowed(
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            reason="loading not allowed",
        )


@dataclass(frozen=True, slots=True)
class _FailingRegisterLoadingFromForm:
    def execute(self, command: RegisterLoadingFromFormCommand) -> object:
        _ = command
        raise MachineOperationsConcurrencyError("race")


@dataclass(frozen=True, slots=True)
class _UnknownPurposeTokenPayload:
    purpose: str
    technician_id: TechnicianId
    machine_id: MachineId
    issued_at: datetime
    nonce: str


def test_loading_submitted_rejects_unknown_token_purpose() -> None:
    def _verify_unknown_purpose(
        token: str,
        secret: str,
    ) -> VerifiedInventoryFormToken:
        _ = token, secret
        return _UnknownPurposeTokenPayload(  # type: ignore[return-value]
            purpose="unknown",
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-unknown",
        )

    client = TestClient(
        build_google_forms_webhook_app(
            GoogleFormsWebhookDeps(
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
                verify_inventory_form_token=_verify_unknown_purpose,
                **warehouse_webhook_dep_kwargs(),
            ),
        ),
    )

    response = _post_loading(
        client,
        payload={
            "form_id": "form-loading",
            "submitted_at": _SUBMITTED_AT.isoformat(),
            "token": "any",
            "answers": _answers_for_token("any"),
        },
    )

    assert response.status_code == 422
    assert "Неизвестный тип формы загрузки" in response.json()["detail"]


def test_loading_submitted_returns_401_on_invalid_webhook_signature() -> None:
    token = _loading_token()
    response = _post_loading(
        _client(),
        payload=_loading_payload(token=token),
        secret="wrong-secret",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_loading_submitted_rejects_oversized_body_before_parsing() -> None:
    body = b"x" * 32
    response = _client(webhook_max_body_bytes=16).post(
        _LOADING_WEBHOOK,
        content=body,
        headers=signed_webhook_headers(body=body, secret=_WEBHOOK_SECRET),
    )

    assert response.status_code == 413


def test_loading_submitted_rejects_oversized_token() -> None:
    response = _post_loading(
        _client(),
        payload=_loading_payload(token="x" * 2049),
    )

    assert response.status_code == 422


def test_loading_webhook_rejects_expired_inventory_token() -> None:
    token = create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2020, 1, 1, tzinfo=UTC),
            nonce="old-nonce",
        ),
        _LOADING_SECRET,
    )
    client = _client(verify_max_age_hours=1.0)
    response = post_signed_webhook(
        client,
        _LOADING_WEBHOOK,
        payload=_loading_payload(token=token),
        secret=_WEBHOOK_SECRET,
    )
    assert response.status_code == 422
    assert "устарел" in response.json()["detail"]


def test_loading_submitted_returns_422_on_invalid_form_token() -> None:
    revision_token = create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-revision",
        ),
        "revision-secret",
    )

    response = _post_loading(
        _client(),
        payload=_loading_payload(token=revision_token),
    )

    assert response.status_code == 422


def test_loading_submitted_returns_409_when_loading_rejected() -> None:
    token = _loading_token()
    response = _post_loading(
        _client(register_loading=_RejectLoadingRegister()),
        payload=_loading_payload(token=token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "loading not allowed"


@dataclass
class _RejectThenAcceptLoadingRegister:
    call_count: int = 0

    def execute(
        self, command: RegisterLoadingFromFormCommand
    ) -> LoadingSubmitted | LoadingNotAllowed:
        self.call_count += 1
        if self.call_count == 1:
            return LoadingNotAllowed(
                technician_id=command.technician_id,
                machine_id=command.machine_id,
                reason="loading not allowed",
            )
        return LoadingSubmitted(
            event_id=EventId("event-loading-retry"),
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            submitted_at=command.submitted_at,
            occurred_at=_SUBMITTED_AT,
            form_id=command.form_id,
            form_token=command.form_token,
        )


def _loading_payload_with_coffee(*, token: str, coffee_value: str) -> dict[str, object]:
    return {
        "form_id": "form-loading",
        "submitted_at": _SUBMITTED_AT.isoformat(),
        "token": token,
        "answers": [
            {"title": "Код заявки.", "value": token},
            {"title": "Кофе", "value": coffee_value},
        ],
    }


def test_loading_submitted_retry_after_rejected_persists_updated_answers() -> None:
    store = InMemoryFormSubmissionStore()
    register = _RejectThenAcceptLoadingRegister()
    client = _client(store=store, register_loading=register)
    token = _loading_token()

    rejected = _post_loading(
        client,
        payload=_loading_payload_with_coffee(token=token, coffee_value="1"),
    )
    accepted = _post_loading(
        client,
        payload=_loading_payload_with_coffee(token=token, coffee_value="5"),
    )

    assert rejected.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["event_id"] == "event-loading-retry"

    snapshot = store.get_by_form_token(token, "loading")
    assert snapshot is not None
    assert snapshot.status == "accepted"
    coffee_answer = next(answer for answer in snapshot.answers if answer.title == "Кофе")
    assert coffee_answer.value == "5"
    assert register.call_count == 2


def test_loading_submitted_returns_409_on_concurrency_conflict() -> None:
    token = _loading_token()
    response = _post_loading(
        _client(register_loading=_FailingRegisterLoadingFromForm()),
        payload=_loading_payload(token=token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == MACHINE_OPERATIONS_CONCURRENCY_REASON


def test_loading_submitted_is_idempotent_for_duplicate_submission() -> None:
    store = InMemoryFormSubmissionStore()
    client = _client(store=store)
    token = _loading_token()

    first = _post_loading(client, payload=_loading_payload(token=token))
    second = _post_loading(client, payload=_loading_payload(token=token))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_id"] == second.json()["event_id"]
    assert store.get_by_form_token(token, "loading") is not None
    assert store.get_by_form_token(token, "loading").status == "accepted"  # type: ignore[union-attr]
