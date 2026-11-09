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
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import PeekedFormToken
from src.domain.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.interfaces.google_forms.webhook.body import _parse_warehouse_inventory_payload
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps
from src.interfaces.google_forms.webhook.helpers import (
    _answers_from_payload,
    _form_token_answer_error,
)
from src.interfaces.google_forms.webhook.notify import _notify_warehouse_submission_error
from src.interfaces.google_forms.webhook.schemas import WarehouseInventorySubmittedResponse
from src.interfaces.google_forms.webhook.signature import _read_verified_webhook_body


@beartype
async def _register_warehouse_inventory_submission(
    deps: GoogleFormsWebhookDeps,
    *,
    form_id: str,
    submitted_at: datetime,
    token: str,
    answers: tuple[FormAnswer, ...],
    peeked: PeekedFormToken,
) -> WarehouseInventorySubmittedResponse:
    answer_error = _form_token_answer_error(
        body_token=token,
        answers=answers,
        field_name=deps.token_field_name,
    )
    if answer_error is not None:
        await _notify_warehouse_submission_error(
            deps,
            technician_id=peeked.technician_id,
            reason=answer_error,
        )
        raise HTTPException(status_code=422, detail=answer_error) from None

    try:
        token_payload = deps.verify_technician_warehouse_inventory_token(
            token,
            deps.technician_warehouse_inventory_form_token_secret,
        )
    except ValueError as error:
        await _notify_warehouse_submission_error(
            deps,
            technician_id=peeked.technician_id,
            reason=str(error),
        )
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        event = await asyncio.to_thread(
            deps.accept_technician_warehouse_inventory.execute,
            form_id=form_id,
            submitted_at=submitted_at,
            form_token=token,
            token_payload=token_payload,
            answers=answers,
        )
    except FormSubmissionRejectedError as error:
        await _notify_warehouse_submission_error(
            deps,
            technician_id=peeked.technician_id,
            reason=error.reason,
        )
        raise HTTPException(status_code=409, detail=error.reason) from error
    except FormSubmissionValidationError as error:
        await _notify_warehouse_submission_error(
            deps,
            technician_id=peeked.technician_id,
            reason=error.reason,
        )
        raise HTTPException(status_code=422, detail=error.reason) from error
    except TechnicianWarehouseConcurrencyError as error:
        await _notify_warehouse_submission_error(
            deps,
            technician_id=peeked.technician_id,
            reason=str(error),
        )
        raise HTTPException(status_code=409, detail=str(error)) from error

    return WarehouseInventorySubmittedResponse(
        status="accepted",
        purpose="technician_warehouse_inventory",
        event_id=event.event_id.value,
        technician_id=event.technician_id.value,
    )


@beartype
def register_warehouse_inventory_routes(app: FastAPI, deps: GoogleFormsWebhookDeps) -> None:
    @app.post(
        "/webhooks/google-forms/technician-warehouse-inventory-submitted",
        response_model=WarehouseInventorySubmittedResponse,
    )
    async def technician_warehouse_inventory_submitted(
        request: Request,
        x_webhook_signature: Annotated[str, Header(alias="X-Webhook-Signature")],
    ) -> WarehouseInventorySubmittedResponse:
        body = await _read_verified_webhook_body(
            request,
            signature_header=x_webhook_signature,
            deps=deps,
        )
        payload = _parse_warehouse_inventory_payload(body)
        answers = _answers_from_payload(payload.answers)
        peeked = deps.peek_form_token(
            payload.token,
            deps.technician_warehouse_inventory_form_token_secret,
        )
        if peeked is None or peeked.purpose != "technician_warehouse_inventory":
            user_detail = format_form_token_field_error(
                "Invalid technician warehouse inventory form token",
                deps.token_field_name,
            )
            if peeked is not None:
                await _notify_warehouse_submission_error(
                    deps,
                    technician_id=peeked.technician_id,
                    reason=user_detail,
                )
            raise HTTPException(status_code=422, detail=user_detail) from None

        return await _register_warehouse_inventory_submission(
            deps,
            form_id=payload.form_id,
            submitted_at=payload.submitted_at,
            token=payload.token,
            answers=answers,
            peeked=peeked,
        )
