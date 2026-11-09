from __future__ import annotations

import hashlib
import hmac
import re
import time

from beartype import beartype

_SIGNATURE_HEADER_PATTERN = re.compile(
    r"^t=(?P<timestamp>\d+),v1=(?P<signature>[0-9a-f]{64})$",
)
_CLOCK_SKEW_SECONDS = 60


class WebhookSignatureError(ValueError):
    """Raised when an incoming webhook signature is missing or invalid."""


@beartype
def build_webhook_signed_message(*, timestamp: int, body: bytes) -> bytes:
    if timestamp < 0:
        raise ValueError("timestamp must not be negative")
    return f"{timestamp}.".encode("ascii") + body


@beartype
def compute_webhook_signature(*, timestamp: int, body: bytes, secret: str) -> str:
    if not secret:
        raise ValueError("webhook secret must not be empty")
    message = build_webhook_signed_message(timestamp=timestamp, body=body)
    return hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


@beartype
def build_webhook_signature_header(
    *,
    body: bytes,
    secret: str,
    timestamp: int | None = None,
) -> str:
    signed_at = int(time.time()) if timestamp is None else timestamp
    signature = compute_webhook_signature(
        timestamp=signed_at,
        body=body,
        secret=secret,
    )
    return f"t={signed_at},v1={signature}"


@beartype
def verify_webhook_signature(
    *,
    body: bytes,
    header_value: str,
    secret: str,
    max_age_seconds: int,
    now: int | None = None,
) -> None:
    if not secret:
        raise ValueError("webhook secret must not be empty")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    match = _SIGNATURE_HEADER_PATTERN.fullmatch(header_value.strip())
    if match is None:
        raise WebhookSignatureError("Invalid webhook signature")

    timestamp = int(match.group("timestamp"))
    provided_signature = match.group("signature")
    expected_signature = compute_webhook_signature(
        timestamp=timestamp,
        body=body,
        secret=secret,
    )
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise WebhookSignatureError("Invalid webhook signature")

    current_time = int(time.time()) if now is None else now
    if timestamp > current_time + _CLOCK_SKEW_SECONDS:
        raise WebhookSignatureError("Invalid webhook signature")
    if current_time - timestamp > max_age_seconds:
        raise WebhookSignatureError("Invalid webhook signature")
