from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from tests.interfaces._warehouse_webhook_dep_fields import warehouse_webhook_dep_kwargs
from tests.interfaces.webhook_request_helpers import post_signed_webhook

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.machine_operations.errors import (
    MACHINE_OPERATIONS_CONCURRENCY_REASON,
    MachineOperationsConcurrencyError,
)
from src.application.machine_operations.use_cases import (
    RegisterLoadingFromFormCommand,
    RegisterRevisionFromFormCommand,
)
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    RevisionFormTokenPayload,
    create_loading_form_token,
    create_revision_form_token,
    verify_inventory_form_token,
    verify_revision_form_token,
)
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    build_google_forms_webhook_app,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier

_TOKEN_SECRET = "test-revision-secret"
_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS = 300
_INVENTORY_TOKEN_SECRET = "test-inventory-secret"
_WEBHOOK_SECRET = "test-webhook-secret"
_MACHINE_ID = MachineId("vm-webhook")
_TECHNICIAN_ID = TechnicianId("tech-webhook")
_LOADING_WEBHOOK = "/webhooks/google-forms/loading-submitted"


@dataclass(frozen=True, slots=True)
class _FailingRegisterRevisionFromForm:
    def execute(
        self,
        command: RegisterRevisionFromFormCommand,
    ) -> object:
        raise MachineOperationsConcurrencyError("race")


@dataclass(frozen=True, slots=True)
class _FailingRegisterLoadingFromForm:
    def execute(
        self,
        command: RegisterLoadingFromFormCommand,
    ) -> object:
        _ = command
        raise MachineOperationsConcurrencyError("race")


@dataclass(frozen=True, slots=True)
class _UnusedAcceptInventory:
    def execute_loading(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("loading webhook must not be called")


@dataclass(frozen=True, slots=True)
class _UnusedAcceptRevision:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("revision webhook must not be called")


def _revision_token() -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-webhook",
        ),
        _TOKEN_SECRET,
    )


def test_revision_webhook_returns_409_on_concurrency_conflict() -> None:
    token = _revision_token()
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    client = TestClient(
        build_google_forms_webhook_app(
            GoogleFormsWebhookDeps(
                accept_revision_form_submission=AcceptRevisionFormSubmissionService(
                    form_submission_store=InMemoryFormSubmissionStore(),
                    register_revision_from_form=_FailingRegisterRevisionFromForm(),
                    product_code_resolver=resolver,
                    form_token_field_name="Код заявки.",
                ),
                accept_inventory_form_submission=_UnusedAcceptInventory(),  # type: ignore[arg-type]
                form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
                token_field_name="Код заявки.",
                webhook_secret=_WEBHOOK_SECRET,
                webhook_signature_max_age_seconds=_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
                revision_form_token_secret=_TOKEN_SECRET,
                inventory_form_token_secret="inventory-secret",
                verify_revision_form_token=verify_revision_form_token,
                verify_inventory_form_token=lambda token, secret: token,  # type: ignore[return-value]
                **warehouse_webhook_dep_kwargs(),
            ),
        ),
    )

    response = post_signed_webhook(
        client,
        "/webhooks/google-forms/revision-submitted",
        payload={
            "form_id": "form-webhook",
            "submitted_at": "2026-05-20T10:00:00Z",
            "revision_token": token,
            "answers": [
                {"title": "Код заявки.", "value": token},
                {"title": "Кофе", "value": "1"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == MACHINE_OPERATIONS_CONCURRENCY_REASON


def _loading_token() -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-loading-webhook",
        ),
        _INVENTORY_TOKEN_SECRET,
    )


def test_loading_webhook_returns_409_on_concurrency_conflict() -> None:
    token = _loading_token()
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    client = TestClient(
        build_google_forms_webhook_app(
            GoogleFormsWebhookDeps(
                accept_revision_form_submission=_UnusedAcceptRevision(),  # type: ignore[arg-type]
                accept_inventory_form_submission=AcceptInventoryFormSubmissionService(
                    form_submission_store=InMemoryFormSubmissionStore(),
                    register_loading_from_form=_FailingRegisterLoadingFromForm(),
                    product_code_resolver=resolver,
                    form_token_field_name="Код заявки.",
                ),
                form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
                token_field_name="Код заявки.",
                webhook_secret=_WEBHOOK_SECRET,
                webhook_signature_max_age_seconds=_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS,
                revision_form_token_secret=_TOKEN_SECRET,
                inventory_form_token_secret=_INVENTORY_TOKEN_SECRET,
                verify_revision_form_token=verify_revision_form_token,
                verify_inventory_form_token=verify_inventory_form_token,
                **warehouse_webhook_dep_kwargs(),
            ),
        ),
    )

    response = post_signed_webhook(
        client,
        _LOADING_WEBHOOK,
        payload={
            "form_id": "form-loading-webhook",
            "submitted_at": "2026-05-20T10:00:00Z",
            "token": token,
            "answers": [
                {"title": "Код заявки.", "value": token},
                {"title": "Кофе", "value": "1"},
            ],
        },
        secret=_WEBHOOK_SECRET,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == MACHINE_OPERATIONS_CONCURRENCY_REASON
