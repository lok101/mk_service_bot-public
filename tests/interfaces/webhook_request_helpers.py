from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from beartype import beartype
from fastapi.testclient import TestClient

from src.domain.webhook_signature import build_webhook_signature_header


@beartype
def serialize_webhook_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8",
    )


@beartype
def signed_webhook_headers(
    *,
    body: bytes,
    secret: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    signed_at = int(time.time()) if timestamp is None else timestamp
    return {
        "Content-Type": "application/json",
        "X-Webhook-Signature": build_webhook_signature_header(
            body=body,
            secret=secret,
            timestamp=signed_at,
        ),
    }


@beartype
def make_recording_to_thread(
    calls: list[str],
) -> Callable[..., Awaitable[Any]]:
    original_to_thread = asyncio.to_thread

    async def recording_to_thread(
        func: Callable[..., Any],
        /,
        *args: object,
        **kwargs: object,
    ) -> Any:
        calls.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    return recording_to_thread


@beartype
def post_signed_webhook(
    client: TestClient,
    url: str,
    *,
    payload: dict[str, Any],
    secret: str,
    timestamp: int | None = None,
) -> Any:
    body = serialize_webhook_json(payload)
    return client.post(
        url,
        content=body,
        headers=signed_webhook_headers(
            body=body,
            secret=secret,
            timestamp=timestamp,
        ),
    )
