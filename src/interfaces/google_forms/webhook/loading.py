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
from src.application.machine_operations import MachineOperationsConcurrencyError
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import VerifiedInventoryFormToken
from src.interfaces.google_forms.webhook.body import _parse_loading_payload
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps
from src.interfaces.google_forms.webhook.helpers import (
    _answers_from_payload,
    _form_token_answer_error,
    _raise_for_concurrency,
    _reject_invalid_form_token,
)
from src.interfaces.google_forms.webhook.notify import (
    _notify_invalid_token,
    _notify_rejection,
    _notify_validation_error,
)
from src.interfaces.google_forms.webhook.schemas import GoogleFormLoadingSubmittedResponse
from src.interfaces.google_forms.webhook.signature import _read_verified_webhook_body


@beartype
async def _register_loading_form_submission(
    deps: GoogleFormsWebhookDeps,
    *,
    form_id: str,
    submitted_at: datetime,
    token: str,
    answers: tuple[FormAnswer, ...],
) -> GoogleFormLoadingSubmittedResponse:
    answer_error = _form_token_answer_error(
        body_token=token,
        answers=answers,
        field_name=deps.token_field_name,
    )
    if answer_error is not None:
        await _notify_invalid_token(
            deps,
            token=token,
            secret=deps.inventory_form_token_secret,
            purpose=None,
            detail=answer_error,
        )
        raise HTTPException(status_code=422, detail=answer_error) from None

    try:
        token_payload = deps.verify_inventory_form_token(
            token,
            deps.inventory_form_token_secret,
        )
    except ValueError as error:
        await _reject_invalid_form_token(
            deps,
            token=token,
            secret=deps.inventory_form_token_secret,
            purpose=None,
            technical_detail=str(error),
        )

    if token_payload.purpose == "loading":
        return await _register_loading(
            deps,
            form_id,
            submitted_at,
            token,
            token_payload,
            answers,
        )

    raise HTTPException(
        status_code=422,
        detail=f"Неизвестный тип формы загрузки: {token_payload.purpose}",
    )


@beartype
async def _register_loading(
    deps: GoogleFormsWebhookDeps,
    form_id: str,
    submitted_at: datetime,
    token: str,
    token_payload: VerifiedInventoryFormToken,
    answers: tuple[FormAnswer, ...],
) -> GoogleFormLoadingSubmittedResponse:
    try:
        result = await asyncio.to_thread(
            deps.accept_inventory_form_submission.execute_loading,
            form_id=form_id,
            submitted_at=submitted_at,
            token=token,
            token_payload=token_payload,
            answers=answers,
        )
    except MachineOperationsConcurrencyError:
        await _raise_for_concurrency(
            deps,
            token=token,
            secret=deps.inventory_form_token_secret,
            purpose="loading",
        )
    except FormSubmissionRejectedError as error:
        await _notify_rejection(
            deps,
            technician_id=token_payload.technician_id,
            machine_id=token_payload.machine_id,
            purpose="loading",
            message=error.reason,
        )
        raise HTTPException(status_code=409, detail=error.reason) from error
    except FormSubmissionValidationError as error:
        await _notify_validation_error(
            deps,
            technician_id=token_payload.technician_id,
            machine_id=token_payload.machine_id,
            purpose="loading",
            message=error.reason,
        )
        raise HTTPException(status_code=422, detail=error.reason) from error

    return GoogleFormLoadingSubmittedResponse(
        status="accepted",
        purpose="loading",
        event_id=result.event_id.value,
        technician_id=result.technician_id.value,
        machine_id=result.machine_id.value,
    )


@beartype
def register_loading_routes(app: FastAPI, deps: GoogleFormsWebhookDeps) -> None:
    @app.post(
        "/webhooks/google-forms/loading-submitted",
        response_model=GoogleFormLoadingSubmittedResponse,
    )
    async def loading_submitted(
        request: Request,
        x_webhook_signature: Annotated[str, Header(alias="X-Webhook-Signature")],
    ) -> GoogleFormLoadingSubmittedResponse:
        body = await _read_verified_webhook_body(
            request,
            signature_header=x_webhook_signature,
            deps=deps,
        )
        payload = _parse_loading_payload(body)

        return await _register_loading_form_submission(
            deps,
            form_id=payload.form_id,
            submitted_at=payload.submitted_at,
            token=payload.token,
            answers=_answers_from_payload(payload.answers),
        )
