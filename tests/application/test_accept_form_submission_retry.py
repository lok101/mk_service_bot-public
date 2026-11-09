from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
    FormSubmissionRejectedError,
)
from src.application.machine_operations.use_cases import (
    RegisterLoadingFromFormCommand,
    RegisterRevisionFromFormCommand,
)
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    InventoryFormTokenPayload,
    RevisionFormTokenPayload,
    create_loading_form_token,
    create_revision_form_token,
    verify_inventory_form_token,
    verify_revision_form_token,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.models import RevisionSource
from src.domain.results import LoadingNotAllowed, RevisionNotAllowed
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver

_FORM_TOKEN_FIELD = "Код заявки."
_LOADING_SECRET = "loading-secret"
_REVISION_SECRET = "revision-secret"
_MACHINE_ID = MachineId("vm-retry")
_TECHNICIAN_ID = TechnicianId("tech-retry")
_SUBMITTED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)


def _loading_token() -> str:
    return create_loading_form_token(
        InventoryFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-loading-retry",
        ),
        _LOADING_SECRET,
    )


def _revision_token() -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-revision-retry",
        ),
        _REVISION_SECRET,
    )


def _loading_answers(token: str, coffee_value: str) -> tuple[FormAnswer, ...]:
    return (
        FormAnswer(title=_FORM_TOKEN_FIELD, value=token),
        FormAnswer(title="Кофе", value=coffee_value),
    )


def _revision_answers(token: str, coffee_value: str) -> tuple[FormAnswer, ...]:
    return _loading_answers(token, coffee_value)


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


@dataclass
class _RejectThenAcceptRevisionRegister:
    call_count: int = 0

    def execute(
        self,
        command: RegisterRevisionFromFormCommand,
    ) -> RevisionCompleted | RevisionNotAllowed:
        self.call_count += 1
        if self.call_count == 1:
            return RevisionNotAllowed(
                technician_id=command.technician_id,
                machine_id=command.machine_id,
                reason="revision not allowed",
            )
        return RevisionCompleted(
            event_id=EventId("event-revision-retry"),
            revision_id=RevisionId("rev-retry"),
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            completed_at=command.submitted_at,
            occurred_at=_SUBMITTED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id=command.form_id,
            form_token=command.form_token,
        )


def test_accept_loading_updates_snapshot_answers_after_rejected_retry() -> None:
    store = InMemoryFormSubmissionStore()
    register = _RejectThenAcceptLoadingRegister()
    service = AcceptInventoryFormSubmissionService(
        form_submission_store=store,
        register_loading_from_form=register,
        product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
        form_token_field_name=_FORM_TOKEN_FIELD,
    )
    token = _loading_token()
    token_payload = verify_inventory_form_token(token, _LOADING_SECRET)

    with pytest.raises(FormSubmissionRejectedError, match="loading not allowed"):
        service.execute_loading(
            form_id="form-loading",
            submitted_at=_SUBMITTED_AT,
            token=token,
            token_payload=token_payload,
            answers=_loading_answers(token, "1"),
        )

    result = service.execute_loading(
        form_id="form-loading",
        submitted_at=_SUBMITTED_AT,
        token=token,
        token_payload=token_payload,
        answers=_loading_answers(token, "5"),
    )

    snapshot = store.get_by_form_token(token, "loading")
    assert snapshot is not None
    assert snapshot.status == "accepted"
    assert snapshot.answers == _loading_answers(token, "5")
    assert result.event_id.value == "event-loading-retry"
    assert register.call_count == 2


def test_accept_revision_updates_snapshot_answers_after_rejected_retry() -> None:
    store = InMemoryFormSubmissionStore()
    register = _RejectThenAcceptRevisionRegister()
    service = AcceptRevisionFormSubmissionService(
        form_submission_store=store,
        register_revision_from_form=register,
        product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
        form_token_field_name=_FORM_TOKEN_FIELD,
    )
    token = _revision_token()
    token_payload = verify_revision_form_token(token, _REVISION_SECRET)

    with pytest.raises(FormSubmissionRejectedError, match="revision not allowed"):
        service.execute(
            form_id="form-revision",
            submitted_at=_SUBMITTED_AT,
            revision_token=token,
            token_payload=token_payload,
            answers=_revision_answers(token, "1000"),
        )

    result = service.execute(
        form_id="form-revision",
        submitted_at=_SUBMITTED_AT,
        revision_token=token,
        token_payload=token_payload,
        answers=_revision_answers(token, "2000"),
    )

    snapshot = store.get_by_form_token(token, "revision")
    assert snapshot is not None
    assert snapshot.status == "accepted"
    assert snapshot.answers == _revision_answers(token, "2000")
    assert result.revision_id.value == "rev-retry"
    assert register.call_count == 2
