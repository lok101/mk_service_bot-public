from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.interfaces.http.bounded_body import read_bounded_request_body


async def _request_with_body(body: bytes, *, content_length: str | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
    }
    if content_length is not None:
        scope["headers"].append((b"content-length", content_length.encode()))

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def test_read_bounded_body_returns_full_payload_within_limit() -> None:
    async def run() -> None:
        body = b'{"ok":true}'
        request = await _request_with_body(body)
        assert await read_bounded_request_body(request, max_body_bytes=1024) == body

    asyncio.run(run())


def test_read_bounded_body_rejects_content_length_over_limit() -> None:
    async def run() -> None:
        request = await _request_with_body(b"", content_length="2048")
        with pytest.raises(HTTPException) as exc:
            await read_bounded_request_body(request, max_body_bytes=1024)
        assert exc.value.status_code == 413

    asyncio.run(run())


def test_read_bounded_body_rejects_stream_over_limit() -> None:
    async def run() -> None:
        request = await _request_with_body(b"x" * 32)
        with pytest.raises(HTTPException) as exc:
            await read_bounded_request_body(request, max_body_bytes=16)
        assert exc.value.status_code == 413

    asyncio.run(run())
