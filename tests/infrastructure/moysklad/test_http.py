from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladAPIError,
    MoySkladConnectionError,
    MoySkladRequestError,
)
from src.infrastructure.integrations.moysklad.http import MoySkladHttpTransport
from src.infrastructure.rate_limiting import (
    AsyncGlobalBackoff,
    AsyncInFlightLimiter,
    AsyncRateLimiter,
    MoySkladApiPriority,
)

_MOCK_BASE_URL = "https://api.moysklad.ru/api/remap/1.2"


def _passthrough_limits() -> tuple[AsyncRateLimiter, AsyncGlobalBackoff, AsyncInFlightLimiter]:
    return (
        AsyncRateLimiter(max_requests=10_000, time_window=1.0),
        AsyncGlobalBackoff(timeout=0.0),
        AsyncInFlightLimiter(max_in_flight=32),
    )


def _make_http(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    request_attempts: int,
    rate_limiter: AsyncRateLimiter | None = None,
    backoff: AsyncGlobalBackoff | None = None,
    in_flight: AsyncInFlightLimiter | None = None,
) -> tuple[MoySkladHttpTransport, httpx.AsyncClient]:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=_MOCK_BASE_URL)
    lim, bo, flight = _passthrough_limits()
    http = MoySkladHttpTransport(
        client=client,
        request_attempts=request_attempts,
        retry_delay_seconds=0.0,
        rate_limiter=rate_limiter if rate_limiter is not None else lim,
        backoff=backoff if backoff is not None else bo,
        in_flight=in_flight if in_flight is not None else flight,
    )
    return http, client


def test_get_parses_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"rows": []})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport,
        base_url=_MOCK_BASE_URL,
        headers={"Authorization": "Bearer test-token"},
    )
    lim, bo, flight = _passthrough_limits()
    http = MoySkladHttpTransport(
        client=client,
        request_attempts=1,
        retry_delay_seconds=0.0,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )

    async def run() -> dict[str, object]:
        return await http.get("/entity/store", params={"limit": 1})

    assert asyncio.run(run()) == {"rows": []}
    asyncio.run(client.aclose())


def test_from_token_builds_client_with_bearer_header() -> None:
    http = MoySkladHttpTransport.from_token(
        access_token="prod-token",
        timeout_seconds=5.0,
        request_attempts=1,
    )
    assert http._client.headers["Authorization"] == "Bearer prod-token"
    assert http._client.headers["Accept-Encoding"] == "gzip"
    asyncio.run(http.aclose())


def test_post_raises_request_error_on_moysklad_errors_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(412, json={"errors": [{"code": 3006, "error": "conflict"}]})

    http, client = _make_http(handler, request_attempts=1)

    async def run() -> None:
        await http.post("/entity/inventory", json={"moment": "2026-01-01 00:00:00"})

    with pytest.raises(MoySkladRequestError) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status == 412
    assert exc_info.value.code == 3006
    assert "conflict" not in str(exc_info.value)
    assert "codes=[3006]" in str(exc_info.value)
    asyncio.run(client.aclose())


def test_get_raises_api_error_on_invalid_json_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.WARNING, logger="src.infrastructure.integrations.moysklad.http")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"not-json")

    http, client = _make_http(handler, request_attempts=1)

    async def run() -> None:
        await http.get("/entity/store")

    with pytest.raises(MoySkladAPIError, match="invalid JSON"):
        asyncio.run(run())
    assert any("moysklad_invalid_json_body" in r.getMessage() for r in caplog.records)
    asyncio.run(client.aclose())


def test_get_retries_on_connect_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    http, client = _make_http(handler, request_attempts=2)

    async def run() -> dict[str, object]:
        return await http.get("/entity/store")

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2
    asyncio.run(client.aclose())


def test_get_does_not_retry_on_http_400() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    http, client = _make_http(handler, request_attempts=3)

    async def run() -> None:
        await http.get("/entity/store")

    with pytest.raises(MoySkladAPIError):
        asyncio.run(run())
    assert calls["count"] == 1
    asyncio.run(client.aclose())


def test_post_does_not_retry_on_timeout() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.TimeoutException("timed out")

    http, client = _make_http(handler, request_attempts=3)

    async def run() -> None:
        await http.post("/entity/demand", json={"externalCode": "x"})

    with pytest.raises(MoySkladConnectionError, match="timed out"):
        asyncio.run(run())
    assert calls["count"] == 1
    asyncio.run(client.aclose())


def test_get_retries_on_timeout() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.TimeoutException("timed out")
        return httpx.Response(200, json={"ok": True})

    http, client = _make_http(handler, request_attempts=2)

    async def run() -> dict[str, object]:
        return await http.get("/entity/store")

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2
    asyncio.run(client.aclose())


def test_post_retries_on_connect_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    http, client = _make_http(handler, request_attempts=2)

    async def run() -> dict[str, object]:
        return await http.post("/entity/demand", json={"externalCode": "x"})

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2
    asyncio.run(client.aclose())


def test_post_does_not_retry_on_network_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.NetworkError("reset", request=request)

    http, client = _make_http(handler, request_attempts=3)

    async def run() -> None:
        await http.post("/entity/demand", json={"externalCode": "x"})

    with pytest.raises(MoySkladConnectionError, match="reset"):
        asyncio.run(run())
    assert calls["count"] == 1
    asyncio.run(client.aclose())


def test_transport_retries_once_on_429_then_succeeds() -> None:
    # happy / error recovery
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"errors": [{"code": 1049}]})
        return httpx.Response(200, json={"ok": True})

    limiter = AsyncRateLimiter(max_requests=10_000, time_window=1.0)
    backoff = AsyncGlobalBackoff(timeout=0.01)
    http, client = _make_http(
        handler,
        request_attempts=1,
        rate_limiter=limiter,
        backoff=backoff,
    )

    async def run() -> dict[str, object]:
        return await http.get("/entity/move/x/positions")

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2
    asyncio.run(client.aclose())


def test_transport_raises_after_second_429() -> None:
    # error
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, json={"errors": [{"code": 1049}]})

    http, client = _make_http(
        handler,
        request_attempts=3,
        rate_limiter=AsyncRateLimiter(max_requests=10_000, time_window=1.0),
        backoff=AsyncGlobalBackoff(timeout=0.0),
    )

    async def run() -> None:
        await http.get("/entity/store")

    with pytest.raises(MoySkladRequestError) as exc_info:
        asyncio.run(run())
    assert exc_info.value.status == 429
    assert calls["count"] == 2
    asyncio.run(client.aclose())


def test_transport_does_not_retry_on_http_400() -> None:
    # edge: 400 без errors-body — MoySkladAPIError, один вызов (регрессия)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    http, client = _make_http(handler, request_attempts=3)

    async def run() -> None:
        await http.get("/entity/store")

    with pytest.raises(MoySkladAPIError):
        asyncio.run(run())
    assert calls["count"] == 1
    asyncio.run(client.aclose())


def test_transport_acquires_rate_limiter_before_get() -> None:
    # happy: acquire зовётся до HTTP
    acquires: list[str] = []

    class RecordingLimiter(AsyncRateLimiter):
        async def acquire(  # noqa: ANN201
            self,
            priority: MoySkladApiPriority | None = None,
        ) -> None:
            acquires.append("acquire")
            await super().acquire(priority)

    def handler(request: httpx.Request) -> httpx.Response:
        acquires.append("http")
        return httpx.Response(200, json={"rows": []})

    http, client = _make_http(
        handler,
        request_attempts=1,
        rate_limiter=RecordingLimiter(max_requests=10_000, time_window=1.0),
        backoff=AsyncGlobalBackoff(timeout=0.0),
    )

    async def run() -> None:
        await http.get("/entity/store")

    asyncio.run(run())
    assert acquires[:2] == ["acquire", "http"]
    asyncio.run(client.aclose())


def test_transport_retries_1073_without_tempo_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error/edge: parallel 1073 retries once; tempo backoff not triggered
    calls = {"count": 0}
    backoff_triggers = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"errors": [{"code": 1073}]})
        return httpx.Response(200, json={"ok": True})

    backoff = AsyncGlobalBackoff(timeout=0.0)
    original = backoff.trigger_backoff

    async def counting_trigger() -> None:
        backoff_triggers["count"] += 1
        await original()

    monkeypatch.setattr(backoff, "trigger_backoff", counting_trigger)
    http, client = _make_http(
        handler,
        request_attempts=1,
        rate_limiter=AsyncRateLimiter(max_requests=10_000, time_window=1.0),
        backoff=backoff,
    )

    async def run() -> dict[str, object]:
        return await http.get("/report/stock/bystore")

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2
    assert backoff_triggers["count"] == 0
    asyncio.run(client.aclose())


def test_transport_1049_triggers_tempo_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # edge: tempo 1049 triggers AsyncGlobalBackoff before retry
    calls = {"count": 0}
    backoff_triggers = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"errors": [{"code": 1049}]})
        return httpx.Response(200, json={"ok": True})

    backoff = AsyncGlobalBackoff(timeout=0.0)
    original = backoff.trigger_backoff

    async def counting_trigger() -> None:
        backoff_triggers["count"] += 1
        await original()

    monkeypatch.setattr(backoff, "trigger_backoff", counting_trigger)
    http, client = _make_http(
        handler,
        request_attempts=1,
        rate_limiter=AsyncRateLimiter(max_requests=10_000, time_window=1.0),
        backoff=backoff,
    )

    async def run() -> dict[str, object]:
        return await http.get("/entity/store")

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2
    assert backoff_triggers["count"] == 1
    asyncio.run(client.aclose())


def test_transport_passes_priority_to_limiter() -> None:
    # happy: GET default LOW, POST default HIGH
    seen: list[MoySkladApiPriority | None] = []

    class RecordingLimiter(AsyncRateLimiter):
        async def acquire(  # noqa: ANN201
            self,
            priority: MoySkladApiPriority | None = None,
        ) -> None:
            seen.append(priority)
            await super().acquire(priority)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    http, client = _make_http(
        handler,
        request_attempts=1,
        rate_limiter=RecordingLimiter(max_requests=10_000, time_window=1.0),
        backoff=AsyncGlobalBackoff(timeout=0.0),
    )

    async def run() -> None:
        await http.get("/entity/store")
        await http.post("/entity/demand", json={"name": "x"})

    asyncio.run(run())
    assert seen == [MoySkladApiPriority.LOW, MoySkladApiPriority.HIGH]
    asyncio.run(client.aclose())
