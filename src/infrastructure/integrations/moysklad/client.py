from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from beartype import beartype

from src.config.moysklad import MoySkladSettings
from src.infrastructure.integrations.moysklad.assortments import (
    AssortmentRef,
    resolve_assortments_by_codes,
)
from src.infrastructure.integrations.moysklad.constants import MOYSKLAD_API_BASE_URL
from src.infrastructure.integrations.moysklad.exceptions import MoySkladValidationError
from src.infrastructure.integrations.moysklad.expand import (
    EXPAND_MAX_LIMIT,
    MOVE_LIST_STORE_EXPAND,
    MOVE_POSITIONS_EXPAND,
    POSITIONS_ASSORTMENT_EXPAND,
)
from src.infrastructure.integrations.moysklad.http import MoySkladHttpTransport
from src.infrastructure.integrations.moysklad.stores import get_store_id_by_code
from src.infrastructure.integrations.moysklad.timezone import format_moment
from src.infrastructure.rate_limiting import (
    AsyncGlobalBackoff,
    AsyncInFlightLimiter,
    AsyncRateLimiter,
)


@beartype
class MoySkladClient:
    def __init__(
        self,
        *,
        settings: MoySkladSettings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        token = settings.api_token
        if token is None or not token.get_secret_value().strip():
            raise MoySkladValidationError("MOYSKLAD_API_TOKEN must not be empty.")
        if http_client is None:
            self._transport = MoySkladHttpTransport.from_token(
                access_token=token.get_secret_value().strip(),
                timeout_seconds=float(settings.request_timeout_seconds),
                request_attempts=settings.request_attempts,
            )
            self._owns_transport = True
        else:
            # Injected clients (unit tests) must not fall back to get_settings()
            # for rate_limiter, backoff, or in_flight.
            self._transport = MoySkladHttpTransport(
                client=http_client,
                request_attempts=settings.request_attempts,
                retry_delay_seconds=float(settings.request_timeout_seconds),
                rate_limiter=AsyncRateLimiter(max_requests=10_000, time_window=1.0),
                backoff=AsyncGlobalBackoff(timeout=0.0),
                in_flight=AsyncInFlightLimiter(max_in_flight=10_000),
            )
            self._owns_transport = False

    @beartype
    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        response = await self._transport.get(
            f"/entity/{entity_path}",
            params={"filter": filter_expr, "limit": limit, "offset": offset},
        )
        rows = response.get("rows") if isinstance(response, dict) else None
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, Mapping)]

    @beartype
    async def post_entity(
        self,
        *,
        entity_path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        response = await self._transport.post(f"/entity/{entity_path}", json=body)
        return response if isinstance(response, Mapping) else {}

    @beartype
    async def put_entity(
        self,
        *,
        entity_path: str,
        entity_id: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        response = await self._transport.put(
            f"/entity/{entity_path}/{entity_id}",
            json=body,
        )
        return response if isinstance(response, Mapping) else {}

    @beartype
    async def delete_entity(
        self,
        *,
        entity_path: str,
        entity_id: str,
    ) -> None:
        await self._transport.delete(f"/entity/{entity_path}/{entity_id}")

    @beartype
    async def get_store_id_by_code(self, code: str) -> UUID:
        return await get_store_id_by_code(self._transport, code)

    @beartype
    async def resolve_assortments_by_codes(self, codes: list[str]) -> dict[str, AssortmentRef]:
        return await resolve_assortments_by_codes(self._transport, codes)

    @beartype
    async def get_stock_report_bystore(
        self,
        *,
        store_id: UUID,
    ) -> list[Mapping[str, Any]]:
        # Paginate: a single limit=1000 page silently truncates large warehouses
        # and made micromarket loading show 0 for SKUs beyond the first page.
        store_href = f"{MOYSKLAD_API_BASE_URL}/entity/store/{store_id}"
        limit = 1000
        offset = 0
        collected: list[Mapping[str, Any]] = []
        while True:
            response = await self._transport.get(
                "/report/stock/bystore",
                params={
                    "filter": f"store={store_href}",
                    "limit": limit,
                    "offset": offset,
                },
            )
            rows = response.get("rows") if isinstance(response, dict) else None
            if not isinstance(rows, list):
                break
            page = [row for row in rows if isinstance(row, Mapping)]
            collected.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return collected

    @beartype
    async def get_inventory_list(
        self,
        *,
        store_id: UUID,
        moment_from: datetime | None,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        store_href = f"{MOYSKLAD_API_BASE_URL}/entity/store/{store_id}"
        filters = [f"store={store_href}"]
        if moment_from is not None:
            filters.append(f"moment>={format_moment(moment_from)}")
        filters.append(f"moment<={format_moment(moment_to)}")
        response = await self._transport.get(
            "/entity/inventory",
            params={
                "filter": ";".join(filters),
                "order": "moment,desc",
                "limit": 100,
            },
        )
        rows = response.get("rows") if isinstance(response, dict) else None
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, Mapping)]

    @beartype
    async def get_inventory_positions(
        self,
        *,
        inventory_id: str,
    ) -> list[Mapping[str, Any]]:
        """List inventory positions with ``assortment`` expanded.

        Pages with ``limit`` ≤ :data:`~.expand.EXPAND_MAX_LIMIT` so the API
        does not silently ignore ``expand``.
        """
        limit = EXPAND_MAX_LIMIT
        offset = 0
        collected: list[Mapping[str, Any]] = []
        while True:
            response = await self._transport.get(
                f"/entity/inventory/{inventory_id}/positions",
                params={
                    "expand": POSITIONS_ASSORTMENT_EXPAND,
                    "limit": limit,
                    "offset": offset,
                },
            )
            rows = response.get("rows") if isinstance(response, dict) else None
            if not isinstance(rows, list):
                break
            page = [row for row in rows if isinstance(row, Mapping)]
            collected.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return collected

    @beartype
    async def get_move_list(
        self,
        *,
        moment_from: datetime,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        """List moves in ``[moment_from, moment_to]``.

        Always requests ``expand=MOVE_LIST_STORE_EXPAND`` with ``limit`` ≤
        ``EXPAND_MAX_LIMIT`` so store ``code`` is on the row (see ``expand``
        module). Do not N+1 ``get_store_code_by_id`` over the window.
        """
        filter_expr = ";".join(
            (
                f"moment>={format_moment(moment_from)}",
                f"moment<={format_moment(moment_to)}",
            ),
        )
        limit = EXPAND_MAX_LIMIT
        offset = 0
        collected: list[Mapping[str, Any]] = []
        while True:
            response = await self._transport.get(
                "/entity/move",
                params={
                    "filter": filter_expr,
                    "expand": MOVE_LIST_STORE_EXPAND,
                    "limit": limit,
                    "offset": offset,
                },
            )
            rows = response.get("rows") if isinstance(response, dict) else None
            if not isinstance(rows, list):
                break
            page = [row for row in rows if isinstance(row, Mapping)]
            collected.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return collected

    @beartype
    async def get_move_positions(
        self,
        *,
        move_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        # Prefer get_moves_by_ids batch expand for warehouse import (LOK-178).
        response = await self._transport.get(
            f"/entity/move/{move_id}/positions",
            params={
                "expand": POSITIONS_ASSORTMENT_EXPAND,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = response.get("rows") if isinstance(response, dict) else None
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, Mapping)]

    @beartype
    async def get_moves_by_ids(
        self,
        *,
        move_ids: tuple[str, ...],
    ) -> list[Mapping[str, Any]]:
        """Re-fetch moves by id with ``expand=positions.assortment`` in chunks."""
        if not move_ids:
            return []
        collected: list[Mapping[str, Any]] = []
        limit = EXPAND_MAX_LIMIT
        for start in range(0, len(move_ids), limit):
            chunk = move_ids[start : start + limit]
            filter_expr = ";".join(f"id={move_id}" for move_id in chunk)
            response = await self._transport.get(
                "/entity/move",
                params={
                    "filter": filter_expr,
                    "expand": MOVE_POSITIONS_EXPAND,
                    "limit": len(chunk),
                },
            )
            rows = response.get("rows") if isinstance(response, dict) else None
            if not isinstance(rows, list):
                continue
            collected.extend(row for row in rows if isinstance(row, Mapping))
        return collected

    @beartype
    async def get_store_code_by_id(self, store_id: UUID) -> str:
        """Fetch one store ``code`` by id.

        Prefer list/document ``expand`` of the store link instead of calling
        this in a loop over a window (rate limit). See ``expand`` module.
        """
        response = await self._transport.get(f"/entity/store/{store_id}")
        if not isinstance(response, Mapping):
            raise MoySkladValidationError(f"Store {store_id} response is invalid.")
        code = response.get("code")
        if not isinstance(code, str) or not code.strip():
            raise MoySkladValidationError(f"Store {store_id} has no code.")
        return code.strip()

    @beartype
    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()
