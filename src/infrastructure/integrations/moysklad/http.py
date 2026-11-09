from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import httpx
from beartype import beartype

from src.config.settings import get_settings
from src.infrastructure.integrations.moysklad.constants import MOYSKLAD_API_BASE_URL
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladAPIError,
    MoySkladConnectionError,
    MoySkladRequestError,
)
from src.infrastructure.rate_limiting import (
    AsyncGlobalBackoff,
    AsyncInFlightLimiter,
    AsyncRateLimiter,
    MoySkladApiPriority,
    PriorityAsyncRateLimiter,
    PrioritySyncRateLimiter,
    SyncGlobalBackoff,
    SyncInFlightLimiter,
)

_LOGGER = logging.getLogger(__name__)
_async_rate_bridge: _AsyncBridgeToSyncPriorityLimiter | None = None
_async_backoff_bridge: _AsyncBridgeToSyncBackoff | None = None
_async_in_flight: AsyncInFlightLimiter | None = None
_sync_rate_limiter: PrioritySyncRateLimiter | None = None
_sync_backoff: SyncGlobalBackoff | None = None
_sync_in_flight: SyncInFlightLimiter | None = None

_PARALLEL_LIMIT_CODE = 1073


class _AsyncBridgeToSyncPriorityLimiter:
    """Async acquire over the process-shared PrioritySyncRateLimiter."""

    def __init__(self, sync: PrioritySyncRateLimiter) -> None:
        self._sync = sync

    async def acquire(self, priority: MoySkladApiPriority | None = None) -> None:
        await asyncio.to_thread(self._sync.acquire, priority)


class _AsyncBridgeToSyncBackoff:
    """Async facade over process-shared SyncGlobalBackoff (1049 tempo)."""

    def __init__(self, sync: SyncGlobalBackoff) -> None:
        self._sync = sync

    async def wait_if_blocked(self) -> None:
        await asyncio.to_thread(self._sync.wait_if_blocked)

    async def trigger_backoff(self, timeout: float | None = None) -> None:
        await asyncio.to_thread(self._sync.trigger_backoff, timeout)

    async def is_blocked(self) -> bool:
        return await asyncio.to_thread(self._sync.is_blocked)


def get_sync_rate_limiter() -> PrioritySyncRateLimiter:
    global _sync_rate_limiter
    if _sync_rate_limiter is None:
        settings = get_settings().moysklad
        _sync_rate_limiter = PrioritySyncRateLimiter(
            max_requests=settings.rate_limit_requests_per_window,
            time_window=settings.rate_limit_window_seconds,
            max_consecutive_high_requests=settings.http_max_consecutive_high,
            high=MoySkladApiPriority.HIGH,
            low=MoySkladApiPriority.LOW,
        )
    return _sync_rate_limiter


def get_sync_backoff() -> SyncGlobalBackoff:
    global _sync_backoff
    if _sync_backoff is None:
        settings = get_settings().moysklad
        _sync_backoff = SyncGlobalBackoff(timeout=settings.rate_limit_backoff_seconds)
    return _sync_backoff


def get_sync_in_flight() -> SyncInFlightLimiter:
    global _sync_in_flight
    if _sync_in_flight is None:
        settings = get_settings().moysklad
        _sync_in_flight = SyncInFlightLimiter(settings.http_max_in_flight)
    return _sync_in_flight


def is_parallel_limit_error(error: MoySkladRequestError) -> bool:
    return _PARALLEL_LIMIT_CODE in error.codes


@runtime_checkable
class _RemapWindowLimiter(Protocol):
    async def acquire(self, priority: MoySkladApiPriority | None = None) -> None: ...


@runtime_checkable
class _RemapAsyncBackoff(Protocol):
    async def wait_if_blocked(self) -> None: ...

    async def trigger_backoff(self, timeout: float | None = None) -> None: ...


def _get_rate_limiter() -> _RemapWindowLimiter:
    global _async_rate_bridge
    if _async_rate_bridge is None:
        _async_rate_bridge = _AsyncBridgeToSyncPriorityLimiter(get_sync_rate_limiter())
    return _async_rate_bridge


def _get_backoff() -> _RemapAsyncBackoff:
    global _async_backoff_bridge
    if _async_backoff_bridge is None:
        _async_backoff_bridge = _AsyncBridgeToSyncBackoff(get_sync_backoff())
    return _async_backoff_bridge


def _get_in_flight() -> AsyncInFlightLimiter:
    global _async_in_flight
    if _async_in_flight is None:
        _async_in_flight = AsyncInFlightLimiter(shared=get_sync_in_flight())
    return _async_in_flight


def _is_moysklad_errors_body(payload: dict[str, Any]) -> bool:
    errors = payload.get("errors")
    return isinstance(errors, list)


@beartype
class MoySkladHttpTransport:
    """HTTP transport for Remap 1.2.

    Retries GET on timeout/connect/network failures. POST retries only
    ``ConnectError`` (request likely never left). POST timeout and other
    ``NetworkError`` raise ``MoySkladConnectionError`` immediately. HTTP 429
    code 1049 triggers tempo AsyncGlobalBackoff + one retry; code 1073 does
    not raise in-flight / skips tempo backoff and retries once after slot
    re-acquire (see MOYSKLAD_HTTP_MAX_IN_FLIGHT / priority). Prefer expand
    to reduce volume; transport backoff is survival, not N+1 elimination.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        request_attempts: int,
        retry_delay_seconds: float,
        rate_limiter: AsyncRateLimiter | PriorityAsyncRateLimiter | None = None,
        backoff: AsyncGlobalBackoff | None = None,
        in_flight: AsyncInFlightLimiter | None = None,
    ) -> None:
        self._client = client
        self._request_attempts = max(1, request_attempts)
        self._retry_delay_seconds = retry_delay_seconds
        self._rate_limiter = rate_limiter
        self._backoff = backoff
        self._in_flight = in_flight

    @classmethod
    @beartype
    def from_token(
        cls,
        *,
        access_token: str,
        timeout_seconds: float,
        request_attempts: int,
        rate_limiter: AsyncRateLimiter | PriorityAsyncRateLimiter | None = None,
        backoff: AsyncGlobalBackoff | None = None,
        in_flight: AsyncInFlightLimiter | None = None,
    ) -> MoySkladHttpTransport:
        client = httpx.AsyncClient(
            base_url=MOYSKLAD_API_BASE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept-Encoding": "gzip",
            },
            timeout=timeout_seconds,
        )
        return cls(
            client=client,
            request_attempts=request_attempts,
            retry_delay_seconds=timeout_seconds,
            rate_limiter=rate_limiter,
            backoff=backoff,
            in_flight=in_flight,
        )

    def _limiter(self) -> _RemapWindowLimiter:
        return self._rate_limiter if self._rate_limiter is not None else _get_rate_limiter()

    def _resolved_backoff(self) -> AsyncGlobalBackoff | _RemapAsyncBackoff:
        return self._backoff if self._backoff is not None else _get_backoff()

    def _resolved_in_flight(self) -> AsyncInFlightLimiter:
        return self._in_flight if self._in_flight is not None else _get_in_flight()

    @beartype
    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        priority: MoySkladApiPriority = MoySkladApiPriority.LOW,
    ) -> Any:
        return await self._request("GET", path, params=params, priority=priority)

    @beartype
    async def post(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        priority: MoySkladApiPriority = MoySkladApiPriority.HIGH,
    ) -> Any:
        return await self._request("POST", path, json=dict(json), priority=priority)

    @beartype
    async def put(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        priority: MoySkladApiPriority = MoySkladApiPriority.HIGH,
    ) -> Any:
        return await self._request("PUT", path, json=dict(json), priority=priority)

    @beartype
    async def delete(
        self,
        path: str,
        *,
        priority: MoySkladApiPriority = MoySkladApiPriority.HIGH,
    ) -> Any:
        return await self._request("DELETE", path, priority=priority)

    @beartype
    async def aclose(self) -> None:
        await self._client.aclose()

    @beartype
    async def _gated_attempt(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None,
        json: dict[str, Any] | None,
        priority: MoySkladApiPriority,
    ) -> Any:
        await self._resolved_backoff().wait_if_blocked()
        await self._limiter().acquire(priority)
        in_flight = self._resolved_in_flight()
        await in_flight.acquire()
        try:
            return await self._request_with_network_retries(
                method,
                path,
                params=params,
                json=json,
            )
        finally:
            in_flight.release()

    @beartype
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
        priority: MoySkladApiPriority = MoySkladApiPriority.LOW,
    ) -> Any:
        try:
            return await self._gated_attempt(
                method,
                path,
                params=params,
                json=json,
                priority=priority,
            )
        except MoySkladRequestError as error:
            if error.status != 429:
                raise
            parallel = is_parallel_limit_error(error)
            _LOGGER.warning(
                "moysklad_rate_limit_backoff path=%s status=%s codes=%s parallel=%s",
                path,
                error.status,
                error.codes,
                parallel,
            )
            if not parallel:
                await self._resolved_backoff().trigger_backoff()
            try:
                return await self._gated_attempt(
                    method,
                    path,
                    params=params,
                    json=json,
                    priority=priority,
                )
            except MoySkladRequestError as retry_error:
                if retry_error.status == 429:
                    _LOGGER.warning(
                        "moysklad_rate_limit_retry_exhausted path=%s codes=%s",
                        path,
                        retry_error.codes,
                    )
                raise

    @beartype
    async def _request_with_network_retries(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._request_attempts + 1):
            try:
                response = await self._client.request(method, path, params=params, json=json)
                return self._parse_response(response)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as error:
                last_error = error
                retry = method.upper() != "POST" or isinstance(error, httpx.ConnectError)
                if not retry or attempt == self._request_attempts:
                    raise MoySkladConnectionError(str(error)) from error
                await asyncio.sleep(self._retry_delay_seconds)
        raise MoySkladConnectionError(str(last_error or "unreachable"))

    @beartype
    def _parse_response(self, response: httpx.Response) -> Any:
        raw = response.content
        payload: dict[str, Any] | None = None
        if raw.strip():
            try:
                parsed = response.json()
            except ValueError as error:
                snippet = raw[:200].decode("utf-8", errors="replace")
                _LOGGER.warning(
                    "moysklad_invalid_json_body status=%s body_len=%s snippet=%r",
                    response.status_code,
                    len(raw),
                    snippet,
                )
                raise MoySkladAPIError(
                    f"MoySklad HTTP {response.status_code}: invalid JSON body",
                ) from error
            payload = parsed if isinstance(parsed, dict) else {"error": parsed}

        if response.status_code >= 400:
            if payload is not None and _is_moysklad_errors_body(payload):
                raise MoySkladRequestError(response.status_code, payload)
            raise MoySkladAPIError(
                f"MoySklad HTTP {response.status_code}: {payload or response.text}",
            )

        if payload is None:
            return {}
        return payload
