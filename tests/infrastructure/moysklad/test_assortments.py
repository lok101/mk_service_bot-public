from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from src.infrastructure.integrations.moysklad.assortments import (
    AssortmentRef,
    resolve_assortments_by_codes,
)
from src.infrastructure.integrations.moysklad.http import MoySkladHttpTransport
from src.infrastructure.rate_limiting import (
    AsyncGlobalBackoff,
    AsyncInFlightLimiter,
    AsyncRateLimiter,
)


def test_resolve_assortments_merges_entity_types() -> None:
    product_id = UUID("33333333-3333-3333-3333-333333333333")
    variant_id = UUID("44444444-4444-4444-4444-444444444444")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/product"):
            return httpx.Response(200, json={"rows": [{"id": str(product_id), "code": "P1"}]})
        if path.endswith("/variant"):
            return httpx.Response(200, json={"rows": [{"id": str(variant_id), "code": "V1"}]})
        if path.endswith("/bundle"):
            return httpx.Response(200, json={"rows": []})
        raise AssertionError(path)

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

    result = asyncio.run(resolve_assortments_by_codes(http, ["P1", "V1"]))
    assert result == {
        "P1": AssortmentRef(id=product_id, entity_type="product"),
        "V1": AssortmentRef(id=variant_id, entity_type="variant"),
    }
    asyncio.run(client.aclose())
