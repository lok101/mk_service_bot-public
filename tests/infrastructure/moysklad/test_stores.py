from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
import pytest

from src.infrastructure.integrations.moysklad.exceptions import MoySkladValidationError
from src.infrastructure.integrations.moysklad.http import MoySkladHttpTransport
from src.infrastructure.integrations.moysklad.stores import get_store_id_by_code
from src.infrastructure.rate_limiting import (
    AsyncGlobalBackoff,
    AsyncInFlightLimiter,
    AsyncRateLimiter,
)


def test_get_store_id_by_code_returns_single_match() -> None:
    store_id = UUID("22222222-2222-2222-2222-222222222222")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("filter") == "code=WH-01"
        return httpx.Response(200, json={"rows": [{"id": str(store_id), "code": "WH-01"}]})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    http = MoySkladHttpTransport(
        client=client,
        request_attempts=1,
        retry_delay_seconds=0.0,
        rate_limiter=AsyncRateLimiter(max_requests=10_000, time_window=1.0),
        backoff=AsyncGlobalBackoff(timeout=0.0),
        in_flight=AsyncInFlightLimiter(max_in_flight=10_000),
    )

    assert asyncio.run(get_store_id_by_code(http, "WH-01")) == store_id
    asyncio.run(client.aclose())


def test_get_store_id_by_code_raises_when_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    http = MoySkladHttpTransport(
        client=client,
        request_attempts=1,
        retry_delay_seconds=0.0,
        rate_limiter=AsyncRateLimiter(max_requests=10_000, time_window=1.0),
        backoff=AsyncGlobalBackoff(timeout=0.0),
        in_flight=AsyncInFlightLimiter(max_in_flight=10_000),
    )

    with pytest.raises(MoySkladValidationError, match="не найден"):
        asyncio.run(get_store_id_by_code(http, "missing"))
    asyncio.run(client.aclose())
