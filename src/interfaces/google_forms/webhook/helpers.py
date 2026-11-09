from __future__ import annotations

from typing import NoReturn

from beartype import beartype
from fastapi import HTTPException

from src.application.form_workflow import (
    find_form_token_in_answers,
    form_token_answer_mismatch_message,
    format_form_token_field_error,
)
from src.application.machine_operations import MACHINE_OPERATIONS_CONCURRENCY_REASON
from src.domain.form_submission import FormAnswer, FormSubmissionPurpose
from src.domain.form_tokens import PeekedFormToken
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps
from src.interfaces.google_forms.webhook.notify import _notify_invalid_token
from src.interfaces.google_forms.webhook.schemas import FormAnswerPayload


@beartype
def _answers_from_payload(
    answers: list[FormAnswerPayload],
) -> tuple[FormAnswer, ...]:
    return tuple(
        FormAnswer(title=answer.title.strip(), value=answer.value.strip()) for answer in answers
    )


@beartype
def _form_token_answer_error(
    *,
    body_token: str,
    answers: tuple[FormAnswer, ...],
    field_name: str,
) -> str | None:
    answer_token = find_form_token_in_answers(answers, field_name)
    if answer_token is None:
        return None
    if answer_token != body_token.strip():
        return form_token_answer_mismatch_message(field_name)
    return None


@beartype
async def _reject_invalid_form_token(
    deps: GoogleFormsWebhookDeps,
    *,
    token: str,
    secret: str,
    purpose: FormSubmissionPurpose | None,
    technical_detail: str,
) -> NoReturn:
    user_detail = format_form_token_field_error(
        technical_detail,
        deps.token_field_name,
    )
    await _notify_invalid_token(
        deps,
        token=token,
        secret=secret,
        purpose=purpose,
        detail=user_detail,
    )
    raise HTTPException(status_code=422, detail=user_detail) from None


@beartype
async def _raise_for_concurrency(
    deps: GoogleFormsWebhookDeps,
    *,
    token: str,
    secret: str,
    purpose: FormSubmissionPurpose | None,
) -> NoReturn:
    await _notify_invalid_token(
        deps,
        token=token,
        secret=secret,
        purpose=purpose,
        detail=MACHINE_OPERATIONS_CONCURRENCY_REASON,
    )
    raise HTTPException(
        status_code=409,
        detail=MACHINE_OPERATIONS_CONCURRENCY_REASON,
    )


@beartype
def _revision_endpoint_purpose_allowed(peeked: PeekedFormToken | None) -> bool:
    return peeked is None or peeked.purpose in {
        None,
        "revision",
    }
