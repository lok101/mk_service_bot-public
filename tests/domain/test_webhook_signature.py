from __future__ import annotations

import pytest

from src.domain.webhook_signature import (
    WebhookSignatureError,
    build_webhook_signature_header,
    compute_webhook_signature,
    verify_webhook_signature,
)

_SECRET = "test-webhook-secret"
_BODY = b'{"form_id":"form-1"}'
_NOW = 1_700_000_000


def test_build_and_verify_round_trip() -> None:
    header = build_webhook_signature_header(
        body=_BODY,
        secret=_SECRET,
        timestamp=_NOW,
    )
    verify_webhook_signature(
        body=_BODY,
        header_value=header,
        secret=_SECRET,
        max_age_seconds=300,
        now=_NOW,
    )


def test_verify_rejects_tampered_body() -> None:
    header = build_webhook_signature_header(
        body=_BODY,
        secret=_SECRET,
        timestamp=_NOW,
    )
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(
            body=b'{"form_id":"tampered"}',
            header_value=header,
            secret=_SECRET,
            max_age_seconds=300,
            now=_NOW,
        )


def test_verify_rejects_wrong_secret() -> None:
    header = build_webhook_signature_header(
        body=_BODY,
        secret=_SECRET,
        timestamp=_NOW,
    )
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(
            body=_BODY,
            header_value=header,
            secret="other-secret",
            max_age_seconds=300,
            now=_NOW,
        )


def test_verify_rejects_expired_timestamp() -> None:
    header = build_webhook_signature_header(
        body=_BODY,
        secret=_SECRET,
        timestamp=_NOW,
    )
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(
            body=_BODY,
            header_value=header,
            secret=_SECRET,
            max_age_seconds=300,
            now=_NOW + 301,
        )


def test_verify_rejects_future_timestamp_beyond_skew() -> None:
    header = build_webhook_signature_header(
        body=_BODY,
        secret=_SECRET,
        timestamp=_NOW + 120,
    )
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(
            body=_BODY,
            header_value=header,
            secret=_SECRET,
            max_age_seconds=300,
            now=_NOW,
        )


def test_verify_rejects_malformed_header() -> None:
    header = build_webhook_signature_header(
        body=_BODY,
        secret=_SECRET,
        timestamp=_NOW,
    )
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(
            body=_BODY,
            header_value=header.replace("v1=", "v2="),
            secret=_SECRET,
            max_age_seconds=300,
            now=_NOW,
        )


def test_compute_signature_is_deterministic() -> None:
    first = compute_webhook_signature(timestamp=_NOW, body=_BODY, secret=_SECRET)
    second = compute_webhook_signature(timestamp=_NOW, body=_BODY, secret=_SECRET)
    assert first == second
    assert len(first) == 64
