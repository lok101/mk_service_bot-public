from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from beartype import beartype
from fastapi import FastAPI, Header, HTTPException, Request

from src.application.form_workflow import format_form_token_field_error
from src.application.micromarket_loading.accept_inventory import VisitFinalizedRecountRejected
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    MicromarketInventoryFormTokenPayload,
    verify_micromarket_inventory_form_token,
)
from src.domain.ids import TechnicianId
from src.interfaces.google_forms.webhook.body import _parse_snack_inventory_payload
from src.interfaces.google_forms.webhook.deps import (
    GoogleFormsWebhookDeps,
    MicromarketInventoryMode,
)
from src.interfaces.google_forms.webhook.helpers import (
    _answers_from_payload,
    _form_token_answer_error,
)
from src.interfaces.google_forms.webhook.inventory_qty_parse import parse_inventory_form_qty
from src.interfaces.google_forms.webhook.notify import _notify_warehouse_submission_error
from src.interfaces.google_forms.webhook.schemas import MicromarketInventorySubmittedResponse
from src.interfaces.google_forms.webhook.signature import _read_verified_webhook_body

_AS_OF_ANSWER_TITLE = "as_of"


@beartype
def _qty_answers(
    *,
    answers: tuple[FormAnswer, ...],
    token_field_name: str,
    mode: MicromarketInventoryMode,
) -> tuple[FormAnswer, ...]:
    filtered: list[FormAnswer] = []
    for answer in answers:
        if answer.title == token_field_name:
            continue
        if mode == "as_of" and answer.title == _AS_OF_ANSWER_TITLE:
            continue
        filtered.append(answer)
    return tuple(filtered)


@beartype
def _parse_as_of_from_answers(answers: tuple[FormAnswer, ...]) -> datetime:
    for answer in answers:
        if answer.title == _AS_OF_ANSWER_TITLE:
            try:
                return datetime.fromisoformat(answer.value)
            except ValueError as error:
                raise HTTPException(
                    status_code=422,
                    detail="as_of must be a valid ISO datetime",
                ) from error
    raise HTTPException(status_code=422, detail="as_of answer is required")


@beartype
def _quantities_from_answers(
    *,
    qty_answers: tuple[FormAnswer, ...],
    product_codes: tuple[str, ...],
    qty_max: int,
) -> dict[str, Decimal]:
    if len(qty_answers) != len(product_codes):
        raise HTTPException(
            status_code=422,
            detail=(f"Expected {len(product_codes)} quantity answers, got {len(qty_answers)}"),
        )
    quantities: dict[str, Decimal] = {}
    for answer, product_code in zip(qty_answers, product_codes, strict=True):
        raw = answer.value.strip()
        if raw == "":
            continue
        try:
            qty = parse_inventory_form_qty(raw)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid quantity for product {product_code!r}",
            ) from error
        if qty < 0:
            raise HTTPException(
                status_code=422,
                detail=f"Quantity must not be negative for product {product_code!r}",
            )
        if qty > qty_max:
            raise HTTPException(
                status_code=422,
                detail=(f"Quantity must not exceed {qty_max} for product {product_code!r}"),
            )
        quantities[product_code] = qty
    return quantities


@beartype
async def _reject_micromarket_inventory(
    deps: GoogleFormsWebhookDeps,
    *,
    technician_id: TechnicianId | None,
    reason: str,
) -> None:
    if technician_id is None:
        return
    await _notify_warehouse_submission_error(
        deps,
        technician_id=technician_id,
        reason=reason,
    )


@beartype
def _verify_token(
    deps: GoogleFormsWebhookDeps,
    *,
    token: str,
    secret: str,
    purpose: Literal["micromarket_inventory_now", "micromarket_inventory_as_of"],
) -> MicromarketInventoryFormTokenPayload:
    if deps.verify_micromarket_inventory_form_token is not None:
        return deps.verify_micromarket_inventory_form_token(
            token,
            secret,
            expected_purpose=purpose,
        )
    return verify_micromarket_inventory_form_token(
        token,
        secret,
        expected_purpose=purpose,
    )


@beartype
async def _register_micromarket_inventory_submission(
    deps: GoogleFormsWebhookDeps,
    *,
    mode: MicromarketInventoryMode,
    form_id: str,
    submitted_at: datetime,
    token: str,
    answers: tuple[FormAnswer, ...],
) -> MicromarketInventorySubmittedResponse:
    purpose: Literal["micromarket_inventory_now", "micromarket_inventory_as_of"]
    if mode == "now":
        purpose = "micromarket_inventory_now"
        secret = deps.micromarket_inventory_now_form_token_secret
    else:
        purpose = "micromarket_inventory_as_of"
        secret = deps.micromarket_inventory_as_of_form_token_secret

    if deps.accept_micromarket_inventory is None or not secret:
        raise HTTPException(
            status_code=503,
            detail="Micromarket inventory webhook is not configured",
        )

    peeked = deps.peek_form_token(token, secret)
    if peeked is None or peeked.purpose != purpose:
        user_detail = format_form_token_field_error(
            f"Invalid micromarket inventory form token for {purpose}",
            deps.token_field_name,
        )
        if peeked is not None:
            await _reject_micromarket_inventory(
                deps,
                technician_id=peeked.technician_id,
                reason=user_detail,
            )
        raise HTTPException(status_code=422, detail=user_detail) from None

    answer_error = _form_token_answer_error(
        body_token=token,
        answers=answers,
        field_name=deps.token_field_name,
    )
    if answer_error is not None:
        await _reject_micromarket_inventory(
            deps,
            technician_id=peeked.technician_id,
            reason=answer_error,
        )
        raise HTTPException(status_code=422, detail=answer_error) from None

    try:
        token_payload = _verify_token(
            deps,
            token=token,
            secret=secret,
            purpose=purpose,
        )
    except ValueError as error:
        await _reject_micromarket_inventory(
            deps,
            technician_id=peeked.technician_id,
            reason=str(error),
        )
        raise HTTPException(status_code=422, detail=str(error)) from error

    as_of_from_form: datetime | None = None
    if mode == "as_of":
        as_of_from_form = _parse_as_of_from_answers(answers)
        if as_of_from_form.tzinfo is None:
            detail = "as_of must be timezone-aware"
            await _reject_micromarket_inventory(
                deps,
                technician_id=token_payload.technician_id,
                reason=detail,
            )
            raise HTTPException(status_code=422, detail=detail) from None
        if as_of_from_form > submitted_at:
            detail = "as_of must not be in the future"
            await _reject_micromarket_inventory(
                deps,
                technician_id=token_payload.technician_id,
                reason=detail,
            )
            raise HTTPException(status_code=422, detail=detail) from None

    qty_answers = _qty_answers(
        answers=answers,
        token_field_name=deps.token_field_name,
        mode=mode,
    )
    try:
        quantities = _quantities_from_answers(
            qty_answers=qty_answers,
            product_codes=token_payload.product_codes,
            qty_max=deps.inventory_form_qty_max,
        )
    except HTTPException as error:
        await _reject_micromarket_inventory(
            deps,
            technician_id=token_payload.technician_id,
            reason=str(error.detail),
        )
        raise

    inventory_id = f"{form_id}:{uuid4()}"

    try:
        await asyncio.to_thread(
            deps.accept_micromarket_inventory.execute,
            machine_code=token_payload.machine_code,
            mode=mode,
            submitted_at=submitted_at,
            quantities=quantities,
            inventory_id=inventory_id,
            as_of_from_form=as_of_from_form,
        )
    except VisitFinalizedRecountRejected as error:
        await _reject_micromarket_inventory(
            deps,
            technician_id=token_payload.technician_id,
            reason=str(error),
        )
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        await _reject_micromarket_inventory(
            deps,
            technician_id=token_payload.technician_id,
            reason=str(error),
        )
        raise HTTPException(status_code=422, detail=str(error)) from error

    return MicromarketInventorySubmittedResponse(
        status="accepted",
        purpose=purpose,
        inventory_id=inventory_id,
        machine_code=token_payload.machine_code,
    )


@beartype
def register_micromarket_inventory_routes(app: FastAPI, deps: GoogleFormsWebhookDeps) -> None:
    @app.post(
        "/webhooks/google-forms/micromarket-inventory-now-submitted",
        response_model=MicromarketInventorySubmittedResponse,
    )
    async def micromarket_inventory_now_submitted(
        request: Request,
        x_webhook_signature: Annotated[str, Header(alias="X-Webhook-Signature")],
    ) -> MicromarketInventorySubmittedResponse:
        body = await _read_verified_webhook_body(
            request,
            signature_header=x_webhook_signature,
            deps=deps,
        )
        payload = _parse_snack_inventory_payload(body)
        answers = _answers_from_payload(payload.answers)
        return await _register_micromarket_inventory_submission(
            deps,
            mode="now",
            form_id=payload.form_id,
            submitted_at=payload.submitted_at,
            token=payload.token,
            answers=answers,
        )

    @app.post(
        "/webhooks/google-forms/micromarket-inventory-as-of-submitted",
        response_model=MicromarketInventorySubmittedResponse,
    )
    async def micromarket_inventory_as_of_submitted(
        request: Request,
        x_webhook_signature: Annotated[str, Header(alias="X-Webhook-Signature")],
    ) -> MicromarketInventorySubmittedResponse:
        body = await _read_verified_webhook_body(
            request,
            signature_header=x_webhook_signature,
            deps=deps,
        )
        payload = _parse_snack_inventory_payload(body)
        answers = _answers_from_payload(payload.answers)
        return await _register_micromarket_inventory_submission(
            deps,
            mode="as_of",
            form_id=payload.form_id,
            submitted_at=payload.submitted_at,
            token=payload.token,
            answers=answers,
        )
