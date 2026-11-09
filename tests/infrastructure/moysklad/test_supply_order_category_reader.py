from __future__ import annotations

from typing import Any

import httpx

from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
)
from src.infrastructure.moysklad.supply_order_category_reader import (
    MoySkladSupplyOrderCategoryReader,
)
from src.infrastructure.rate_limiting import (
    SyncGlobalBackoff,
    SyncInFlightLimiter,
    SyncRateLimiter,
)


def _passthrough() -> tuple[SyncRateLimiter, SyncGlobalBackoff, SyncInFlightLimiter]:
    return (
        SyncRateLimiter(max_requests=10_000, time_window=1.0),
        SyncGlobalBackoff(timeout=0.0),
        SyncInFlightLimiter(max_in_flight=32),
    )


_ATTR = "c3b612d9-cc7d-11f1-0a80-1d46001735af"
_READY = "7203a901-b1b2-11f1-0a80-115a00344501"
_CHILD = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_DEEP = "dddddddd-eeee-ffff-aaaa-bbbbbbbbbbbb"
_MID = "cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa"


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        for pattern, payload in self._routes.items():
            if pattern in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"errors": [{"error": "missing"}]})


def test_reader_uses_nested_expand_without_folder_get() -> None:
    transport = _FakeTransport(
        {
            "/entity/product?": {
                "rows": [
                    {
                        "id": "prod-1",
                        "code": "ms-2311",
                        "attributes": [{"id": _ATTR, "value": 5}],
                        "productFolder": {
                            "id": _CHILD,
                            "name": "leaf",
                            "productFolder": {
                                "id": _READY,
                                "name": "ready",
                            },
                        },
                    },
                ],
            },
        },
    )
    client = httpx.Client(transport=transport, base_url="https://api.moysklad.ru/api/remap/1.2")
    lim, bo, flight = _passthrough()
    reader = MoySkladSupplyOrderCategoryReader(
        http_client=client,
        attr_shelf_life_days_id=_ATTR,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    result = reader.fetch_by_catalog_codes(("ms-2311",))
    assert not isinstance(result, SupplyOrderCategoryFactsFetchFailed)
    assert len(result) == 1
    assert result[0].catalog_code == "ms-2311"
    assert result[0].shelf_life_days == 5
    assert result[0].folder_ancestor_ids[0] == _CHILD
    assert _READY in result[0].folder_ancestor_ids
    nested = "productFolder.productFolder.productFolder"
    assert any(
        nested in url
        or nested.replace(".", "%2E") in url
        or "expand=attributes%2CproductFolder" in url
        for url in transport.calls
    )
    assert not any("/entity/productfolder/" in url for url in transport.calls)


def test_reader_depth_beyond_expand_uses_folder_index() -> None:
    transport = _FakeTransport(
        {
            "/entity/product?": {
                "rows": [
                    {
                        "id": "prod-1",
                        "code": "ms-deep",
                        "attributes": [{"id": _ATTR, "value": 3}],
                        "productFolder": {
                            "id": _DEEP,
                            "name": "d3",
                            "productFolder": {
                                "id": _MID,
                                "name": "d2",
                                "productFolder": {
                                    "id": _CHILD,
                                    "name": "d1",
                                    "productFolder": {
                                        "meta": {
                                            "href": (
                                                "https://api.moysklad.ru/api/remap/1.2/"
                                                f"entity/productfolder/{_READY}"
                                            ),
                                        },
                                    },
                                },
                            },
                        },
                    },
                ],
            },
        },
    )
    client = httpx.Client(transport=transport, base_url="https://api.moysklad.ru/api/remap/1.2")
    lim, bo, flight = _passthrough()
    reader = MoySkladSupplyOrderCategoryReader(
        http_client=client,
        attr_shelf_life_days_id=_ATTR,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    reader.set_folder_parent_index({_CHILD: _READY, _READY: None})
    result = reader.fetch_by_catalog_codes(("ms-deep",))
    assert not isinstance(result, SupplyOrderCategoryFactsFetchFailed)
    assert _READY in result[0].folder_ancestor_ids
    assert not any("/entity/productfolder/" in url for url in transport.calls)


def test_reader_http_error_fail_closed() -> None:
    class Boom(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

    client = httpx.Client(transport=Boom(), base_url="https://api.moysklad.ru/api/remap/1.2")
    lim, bo, flight = _passthrough()
    reader = MoySkladSupplyOrderCategoryReader(
        http_client=client,
        attr_shelf_life_days_id=_ATTR,
        request_attempts=1,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    result = reader.fetch_by_catalog_codes(("ms-2311",))
    assert isinstance(result, SupplyOrderCategoryFactsFetchFailed)


def test_reader_meta_only_product_folder_fail_closed() -> None:
    transport = _FakeTransport(
        {
            "/entity/product?": {
                "rows": [
                    {
                        "id": "prod-1",
                        "code": "ms-meta",
                        "attributes": [{"id": _ATTR, "value": 1}],
                        "productFolder": {
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/productfolder/{_READY}"
                                ),
                            },
                        },
                    },
                ],
            },
        },
    )
    client = httpx.Client(transport=transport, base_url="https://api.moysklad.ru/api/remap/1.2")
    lim, bo, flight = _passthrough()
    reader = MoySkladSupplyOrderCategoryReader(
        http_client=client,
        attr_shelf_life_days_id=_ATTR,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    result = reader.fetch_by_catalog_codes(("ms-meta",))
    assert isinstance(result, SupplyOrderCategoryFactsFetchFailed)
    assert not any("/entity/productfolder/" in url for url in transport.calls)


def test_reader_refresh_folder_parent_index_pages_list() -> None:
    transport = _FakeTransport(
        {
            "/entity/productfolder?": {
                "rows": [
                    {
                        "id": _DEEP,
                        "productFolder": {
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/productfolder/{_MID}"
                                ),
                            },
                        },
                    },
                    {
                        "id": _MID,
                        "productFolder": {
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/productfolder/{_CHILD}"
                                ),
                            },
                        },
                    },
                    {
                        "id": _CHILD,
                        "productFolder": {
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/productfolder/{_READY}"
                                ),
                            },
                        },
                    },
                    {"id": _READY},
                ],
            },
            "/entity/product?": {
                "rows": [
                    {
                        "id": "prod-1",
                        "code": "ms-deep",
                        "attributes": [{"id": _ATTR, "value": 3}],
                        "productFolder": {
                            "id": _DEEP,
                            "name": "d3",
                            "productFolder": {
                                "id": _MID,
                                "name": "d2",
                                "productFolder": {
                                    "id": _CHILD,
                                    "name": "d1",
                                    "productFolder": {
                                        "meta": {
                                            "href": (
                                                "https://api.moysklad.ru/api/remap/1.2/"
                                                f"entity/productfolder/{_READY}"
                                            ),
                                        },
                                    },
                                },
                            },
                        },
                    },
                ],
            },
        },
    )
    client = httpx.Client(transport=transport, base_url="https://api.moysklad.ru/api/remap/1.2")
    lim, bo, flight = _passthrough()
    reader = MoySkladSupplyOrderCategoryReader(
        http_client=client,
        attr_shelf_life_days_id=_ATTR,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    reader.refresh_folder_parent_index()
    result = reader.fetch_by_catalog_codes(("ms-deep",))
    assert not isinstance(result, SupplyOrderCategoryFactsFetchFailed)
    assert _READY in result[0].folder_ancestor_ids
    assert any("/entity/productfolder?" in url for url in transport.calls)
    assert not any("/entity/productfolder/" in url for url in transport.calls)
