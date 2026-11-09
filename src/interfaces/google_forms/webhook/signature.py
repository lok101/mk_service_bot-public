from __future__ import annotations

from beartype import beartype
from fastapi import HTTPException, Request

from src.domain.webhook_signature import (
    WebhookSignatureError,
    verify_webhook_signature,
)
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps
from src.interfaces.http.bounded_body import read_bounded_request_body


@beartype
async def _read_verified_webhook_body(
    request: Request,
    *,
    signature_header: str,
    deps: GoogleFormsWebhookDeps,
) -> bytes:
    body = await read_bounded_request_body(
        request,
        max_body_bytes=deps.webhook_max_body_bytes,
    )
    try:
        verify_webhook_signature(
            body=body,
            header_value=signature_header,
            secret=deps.webhook_secret,
            max_age_seconds=deps.webhook_signature_max_age_seconds,
        )
    except WebhookSignatureError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return body
