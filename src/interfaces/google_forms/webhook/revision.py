from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

from beartype import beartype
from fastapi import FastAPI, Header, HTTPException, Request

from src.application.form_submissions import (
    FormSubmissionRejectedError,
    FormSubmissionValidationError,
)
from src.application.form_workflow import format_form_token_field_error
from src.application.machine_operations import MachineOperationsConcurrencyError
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import PeekedFormToken
from src.interfaces.google_forms.webhook.body import _parse_revision_payload
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps
from src.interfaces.google_forms.webhook.helpers import (
    _answers_from_payload,
    _form_token_answer_error,
    _raise_for_concurrency,
    _reject_invalid_form_token,
    _revision_endpoint_purpose_allowed,
)
from src.interfaces.google_forms.webhook.notify import (
    _notify_invalid_token,
    _notify_rejection,
    _notify_validation_error,
    _notify_warehouse_submission_error,
)
from src.interfaces.google_forms.webhook.schemas import GoogleFormRevisionSubmittedResponse
from src.interfaces.google_forms.webhook.signature import _read_verified_webhook_body


@beartype
async def _register_revision_form_submission(
    deps: GoogleFormsWebhookDeps,
    *,
    form_id: str,
    submitted_at: datetime,
    token: str,
    answers: tuple[FormAnswer, ...],
    peeked: PeekedFormToken | None,
) -> GoogleFormRevisionSubmittedResponse:
    answer_error = _form_token_answer_error(
        body_token=token,
        answers=answers,
        field_name=deps.token_field_name,
    )
    if answer_error is not None:
        await _notify_invalid_token(
            deps,
            token=token,
            secret=deps.revision_form_token_secret,
            purpose="revision",
            detail=answer_error,
        )
        raise HTTPException(status_code=422, detail=answer_error) from None

    try:
        token_payload = deps.verify_revision_form_token(
            token,
            deps.revision_form_token_secret,
        )
    except ValueError as error:
        user_detail = format_form_token_field_error(
            str(error),
            deps.token_field_name,
        )
        if peeked is None:
            raise HTTPException(status_code=422, detail=user_detail) from error
        await _reject_invalid_form_token(
            deps,
            token=token,
            secret=deps.revision_form_token_secret,
            purpose="revision",
            technical_detail=str(error),
        )

    try:
        event = await asyncio.to_thread(
            deps.accept_revision_form_submission.execute,
            form_id=form_id,
            submitted_at=submitted_at,
            revision_token=token,
            token_payload=token_payload,
            answers=answers,
        )
    except MachineOperationsConcurrencyError:
        await _raise_for_concurrency(
            deps,
            token=token,
            secret=deps.revision_form_token_secret,
            purpose="revision",
        )
    except FormSubmissionRejectedError as error:
        await _notify_rejection(
            deps,
            technician_id=token_payload.technician_id,
            machine_id=token_payload.machine_id,
            purpose="revision",
            message=error.reason,
        )
        raise HTTPException(status_code=409, detail=error.reason) from error
    except FormSubmissionValidationError as error:
        await _notify_validation_error(
            deps,
            technician_id=token_payload.technician_id,
            machine_id=token_payload.machine_id,
            purpose="revision",
            message=error.reason,
        )
        raise HTTPException(status_code=422, detail=error.reason) from error

    return GoogleFormRevisionSubmittedResponse(
        status="accepted",
        event_id=event.event_id.value,
        revision_id=event.revision_id.value,
        technician_id=event.technician_id.value,
        machine_id=event.machine_id.value,
    )


@beartype
def register_revision_routes(app: FastAPI, deps: GoogleFormsWebhookDeps) -> None:
    @app.post(
        "/webhooks/google-forms/revision-submitted",
        response_model=GoogleFormRevisionSubmittedResponse,
    )
    async def revision_submitted(
        request: Request,
        x_webhook_signature: Annotated[str, Header(alias="X-Webhook-Signature")],
    ) -> GoogleFormRevisionSubmittedResponse:
        body = await _read_verified_webhook_body(
            request,
            signature_header=x_webhook_signature,
            deps=deps,
        )
        payload = _parse_revision_payload(body)
        answers = _answers_from_payload(payload.answers)
        peeked = deps.peek_form_token(
            payload.revision_token,
            deps.revision_form_token_secret,
        )

        if not _revision_endpoint_purpose_allowed(peeked):
            if peeked is not None:
                await _notify_warehouse_submission_error(
                    deps,
                    technician_id=peeked.technician_id,
                    reason="Revision form token purpose is invalid",
                )
            raise HTTPException(
                status_code=422,
                detail="Revision form token purpose is invalid",
            )

        return await _register_revision_form_submission(
            deps,
            form_id=payload.form_id,
            submitted_at=payload.submitted_at,
            token=payload.revision_token,
            answers=answers,
            peeked=peeked,
        )
