from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import SecretStr

from src.config.moysklad import MoySkladSettings
from src.infrastructure.integrations.moysklad.client import MoySkladClient
from src.infrastructure.integrations.moysklad.expand import (
    EXPAND_MAX_LIMIT,
    MOVE_LIST_STORE_EXPAND,
    POSITIONS_ASSORTMENT_EXPAND,
)


def test_client_get_entity_list_uses_filter_param() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["filter"] = str(request.url.params.get("filter"))
        return httpx.Response(200, json={"rows": [{"id": "abc", "externalCode": "x"}]})

    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        request_timeout_seconds=5,
        request_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    underlying = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    client = MoySkladClient(settings=settings, http_client=underlying)

    rows = asyncio.run(
        client.get_entity_list(
            entity_path="inventory",
            filter_expr="externalCode=mk-service-bot:evt:inventory",
            limit=1,
        ),
    )
    assert captured["filter"] == "externalCode=mk-service-bot:evt:inventory"
    assert rows[0]["externalCode"] == "x"
    asyncio.run(client.aclose())


def test_get_inventory_positions_uses_expand_with_limit_at_most_expand_max() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "expand": request.url.params.get("expand"),
                "limit": int(request.url.params.get("limit") or 0),
                "offset": int(request.url.params.get("offset") or 0),
            },
        )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "assortment": {"id": "p1", "code": "SKU-1"},
                        "quantity": 1,
                    },
                ],
            },
        )

    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        request_timeout_seconds=5,
        request_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    underlying = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    client = MoySkladClient(settings=settings, http_client=underlying)

    rows = asyncio.run(client.get_inventory_positions(inventory_id="inv-1"))

    assert len(captured) == 1
    assert captured[0]["path"].endswith("/entity/inventory/inv-1/positions")
    assert captured[0]["expand"] == POSITIONS_ASSORTMENT_EXPAND
    assert captured[0]["limit"] == EXPAND_MAX_LIMIT
    assert captured[0]["limit"] <= EXPAND_MAX_LIMIT
    assert rows[0]["assortment"]["code"] == "SKU-1"
    asyncio.run(client.aclose())


def test_get_move_list_uses_store_expand_with_limit_at_most_expand_max() -> None:
    """happy: каждая страница GET /entity/move с expand stores и limit≤100."""
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "expand": request.url.params.get("expand"),
                "limit": int(request.url.params.get("limit") or 0),
                "offset": int(request.url.params.get("offset") or 0),
                "filter": request.url.params.get("filter"),
            },
        )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "id": "move-1",
                        "sourceStore": {"id": "s1", "code": "main"},
                        "targetStore": {"id": "s2", "code": "tech-1"},
                    },
                ],
            },
        )

    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        request_timeout_seconds=5,
        request_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    underlying = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    client = MoySkladClient(settings=settings, http_client=underlying)

    moment_from = datetime(2026, 5, 1, tzinfo=UTC)
    moment_to = datetime(2026, 7, 1, tzinfo=UTC)
    rows = asyncio.run(
        client.get_move_list(moment_from=moment_from, moment_to=moment_to),
    )

    assert len(captured) == 1
    assert captured[0]["path"].endswith("/entity/move")
    assert captured[0]["expand"] == MOVE_LIST_STORE_EXPAND
    assert MOVE_LIST_STORE_EXPAND == "sourceStore,targetStore"
    assert captured[0]["limit"] == EXPAND_MAX_LIMIT
    assert captured[0]["limit"] <= EXPAND_MAX_LIMIT
    assert captured[0]["offset"] == 0
    assert captured[0]["filter"] is not None
    assert "moment>=" in str(captured[0]["filter"])
    assert rows[0]["id"] == "move-1"
    asyncio.run(client.aclose())


def test_get_stock_report_bystore_paginates_until_short_page() -> None:
    from uuid import UUID

    store_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    pages: list[list[dict[str, Any]]] = [
        [{"id": f"row-{i}", "code": f"C{i}"} for i in range(1000)],
        [{"id": "row-last", "code": "CLAST"}],
    ]
    offsets_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/report/stock/bystore")
        offset = int(request.url.params.get("offset") or 0)
        offsets_seen.append(offset)
        page_index = offset // 1000
        return httpx.Response(200, json={"rows": pages[page_index]})

    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        request_timeout_seconds=5,
        request_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    underlying = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    client = MoySkladClient(settings=settings, http_client=underlying)

    rows = asyncio.run(client.get_stock_report_bystore(store_id=store_id))

    assert offsets_seen == [0, 1000]
    assert len(rows) == 1001
    assert rows[-1]["code"] == "CLAST"
    asyncio.run(client.aclose())


def test_get_inventory_positions_paginates_until_short_page() -> None:
    pages: list[list[dict[str, Any]]] = [
        [{"id": f"pos-{i}"} for i in range(EXPAND_MAX_LIMIT)],
        [{"id": "pos-last"}],
    ]
    offsets_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset") or 0)
        offsets_seen.append(offset)
        page_index = offset // EXPAND_MAX_LIMIT
        return httpx.Response(200, json={"rows": pages[page_index]})

    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        request_timeout_seconds=5,
        request_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    underlying = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.moysklad.ru/api/remap/1.2",
    )
    client = MoySkladClient(settings=settings, http_client=underlying)

    rows = asyncio.run(client.get_inventory_positions(inventory_id="inv-2"))

    assert offsets_seen == [0, EXPAND_MAX_LIMIT]
    assert len(rows) == EXPAND_MAX_LIMIT + 1
    assert rows[-1]["id"] == "pos-last"
    asyncio.run(client.aclose())
