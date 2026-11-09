from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.application.form_submissions.accept import AcceptRevisionFormSubmissionService
from src.application.machine_operations.use_cases import RegisterRevisionFromFormCommand
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    RevisionFormTokenPayload,
    create_revision_form_token,
    verify_revision_form_token,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.domain.results import RevisionNotAllowed
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver

_FORM_TOKEN_FIELD = "Код заявки."
_REVISION_SECRET = "revision-secret-flow"
_MACHINE_ID = MachineId("vm-flow")
_TECHNICIAN_ID = TechnicianId("tech-flow")
_SUBMITTED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)


def _revision_token() -> str:
    return create_revision_form_token(
        RevisionFormTokenPayload(
            technician_id=_TECHNICIAN_ID,
            machine_id=_MACHINE_ID,
            issued_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            nonce="nonce-flow",
        ),
        _REVISION_SECRET,
    )


def _answers(token: str, coffee_value: str) -> tuple[FormAnswer, ...]:
    return (
        FormAnswer(title=_FORM_TOKEN_FIELD, value=token),
        FormAnswer(title="Кофе", value=coffee_value),
    )


@dataclass
class _AcceptOnceRevisionRegister:
    call_count: int = 0

    def execute(
        self, command: RegisterRevisionFromFormCommand
    ) -> RevisionCompleted | RevisionNotAllowed:
        self.call_count += 1
        return RevisionCompleted(
            event_id=EventId("event-flow"),
            revision_id=RevisionId("rev-flow"),
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            completed_at=command.submitted_at,
            occurred_at=_SUBMITTED_AT,
            source=RevisionSource.GOOGLE_FORM,
            form_id=command.form_id,
            form_token=command.form_token,
        )


def test_accepted_revision_replay_with_invalid_answers_returns_cached_event() -> None:
    store = InMemoryFormSubmissionStore()
    register = _AcceptOnceRevisionRegister()
    service = AcceptRevisionFormSubmissionService(
        form_submission_store=store,
        register_revision_from_form=register,
        product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
        form_token_field_name=_FORM_TOKEN_FIELD,
    )
    token = _revision_token()
    token_payload = verify_revision_form_token(token, _REVISION_SECRET)

    first = service.execute(
        form_id="form-revision",
        submitted_at=_SUBMITTED_AT,
        revision_token=token,
        token_payload=token_payload,
        answers=_answers(token, "2000"),
    )

    # Повтор уже принятой формы с невалидными ответами (пустое значение) —
    # idempotency-check выполняется до валидации, возвращается кэшированное событие.
    second = service.execute(
        form_id="form-revision",
        submitted_at=_SUBMITTED_AT,
        revision_token=token,
        token_payload=token_payload,
        answers=_answers(token, ""),
    )

    assert first.event_id.value == "event-flow"
    assert second.event_id.value == "event-flow"
    assert register.call_count == 1
