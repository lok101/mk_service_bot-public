from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from src.infrastructure.moysklad.purchase_prices.http_client import (
    MoySkladPurchasePricesHttpClient,
)
from src.infrastructure.moysklad.purchase_prices.models import LastSupplyProcurementRow
from src.infrastructure.rate_limiting import (
    SyncGlobalBackoff,
    SyncInFlightLimiter,
    SyncRateLimiter,
)

_STORE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_PRODUCT_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_AGENT_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
_PACKAGE_ATTR_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
_SUPPLIER_NAME_ATTR_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def _client(
    handler: object,
    *,
    package_quantity_attr_id: str = "",
    supplier_product_name_attr_id: str = "",
) -> MoySkladPurchasePricesHttpClient:
    return MoySkladPurchasePricesHttpClient(
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
            base_url="https://api.moysklad.ru/api/remap/1.2",
        ),
        main_store_id=_STORE_ID,
        supply_fetch_concurrency=1,
        request_attempts=1,
        retry_delay_seconds=0.0,
        package_quantity_attr_id=package_quantity_attr_id,
        supplier_product_name_attr_id=supplier_product_name_attr_id,
        rate_limiter=SyncRateLimiter(max_requests=10_000, time_window=1.0),
        backoff=SyncGlobalBackoff(timeout=0.0),
        in_flight=SyncInFlightLimiter(max_in_flight=32),
    )


def test_fetch_last_supply_procurement_reads_agent_max_price_and_moment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        assert request.url.path.endswith("/entity/supply")
        expand = str(request.url.params.get("expand", ""))
        assert "agent" in expand
        assert "positions.assortment" in expand
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "agent": {
                            "id": _AGENT_UUID,
                            "name": "ООО Поставщик",
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/counterparty/{_AGENT_UUID}"
                                ),
                                "type": "counterparty",
                            },
                        },
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1000},
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1250},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(handler).fetch_last_supply_procurement("2311")
    assert row == LastSupplyProcurementRow(
        catalog_code="2311",
        supplier_id=_AGENT_UUID,
        supplier_name="ООО Поставщик",
        last_buy_price=Decimal("12.5"),
        supply_moment=datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
    )


def test_fetch_last_supply_procurement_empty_supply_is_none_not_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        return httpx.Response(200, json={"rows": []})

    row = _client(handler).fetch_last_supply_procurement("2311")
    assert row is not None
    assert row.last_buy_price is None
    assert row.supplier_id is None
    assert row.supply_moment is None


def test_fetch_last_supply_procurement_without_agent_keeps_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 2000},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(handler).fetch_last_supply_procurement("2311")
    assert row is not None
    assert row.last_buy_price == Decimal("20")
    assert row.supplier_id is None
    assert row.supplier_name is None
    assert row.supply_moment == datetime(2026, 10, 4, 9, 30, tzinfo=UTC)


def test_fetch_last_supply_procurement_http_fail_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        return httpx.Response(500, json={"errors": [{"error": "boom"}]})

    assert _client(handler).fetch_last_supply_procurement("2311") is None


def test_fetch_last_supply_procurement_missing_product_is_empty_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/entity/product")
        return httpx.Response(200, json={"rows": []})

    row = _client(handler).fetch_last_supply_procurement("2311")
    assert row == LastSupplyProcurementRow(
        catalog_code="2311",
        supplier_id=None,
        supplier_name=None,
        last_buy_price=None,
        supply_moment=None,
    )


def test_fetch_last_supply_procurement_reads_product_custom_attrs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        if path.endswith(f"/entity/product/{_PRODUCT_UUID}"):
            return httpx.Response(
                200,
                json={
                    "id": _PRODUCT_UUID,
                    "attributes": [
                        {"id": _PACKAGE_ATTR_ID, "value": 6},
                        {"id": _SUPPLIER_NAME_ATTR_ID, "value": "Салат у поставщика"},
                        {"id": "unrelated-attr", "value": "ignore"},
                    ],
                },
            )
        assert path.endswith("/entity/supply")
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "agent": {
                            "id": _AGENT_UUID,
                            "name": "ООО Поставщик",
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/counterparty/{_AGENT_UUID}"
                                ),
                                "type": "counterparty",
                            },
                        },
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1250},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(
        handler,
        package_quantity_attr_id=_PACKAGE_ATTR_ID,
        supplier_product_name_attr_id=_SUPPLIER_NAME_ATTR_ID,
    ).fetch_last_supply_procurement("2311")
    assert row == LastSupplyProcurementRow(
        catalog_code="2311",
        supplier_id=_AGENT_UUID,
        supplier_name="ООО Поставщик",
        last_buy_price=Decimal("12.5"),
        supply_moment=datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        package_quantity=Decimal("6"),
        supplier_product_name="Салат у поставщика",
    )


def test_fetch_last_supply_procurement_without_attr_ids_skips_product_detail() -> None:
    detail_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_hits
        path = request.url.path
        if path.endswith(f"/entity/product/{_PRODUCT_UUID}"):
            detail_hits += 1
            return httpx.Response(200, json={"id": _PRODUCT_UUID, "attributes": []})
        if path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1000},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(handler).fetch_last_supply_procurement("2311")
    assert detail_hits == 0
    assert row is not None
    assert row.package_quantity is None
    assert row.supplier_product_name is None


def test_fetch_last_supply_procurement_attrs_from_list_skips_detail() -> None:
    # happy: attributes already on list row → no GET product/{id}
    detail_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_hits
        path = request.url.path
        if path.endswith(f"/entity/product/{_PRODUCT_UUID}"):
            detail_hits += 1
            return httpx.Response(500, json={"errors": [{"error": "should not call detail"}]})
        if path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "id": _PRODUCT_UUID,
                            "code": "2311",
                            "volume": 1,
                            "attributes": [
                                {"id": _PACKAGE_ATTR_ID, "value": 6},
                                {"id": _SUPPLIER_NAME_ATTR_ID, "value": "Салат у поставщика"},
                            ],
                        }
                    ]
                },
            )
        assert path.endswith("/entity/supply")
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "agent": {
                            "id": _AGENT_UUID,
                            "name": "ООО Поставщик",
                            "meta": {
                                "href": (
                                    "https://api.moysklad.ru/api/remap/1.2/"
                                    f"entity/counterparty/{_AGENT_UUID}"
                                ),
                                "type": "counterparty",
                            },
                        },
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1250},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(
        handler,
        package_quantity_attr_id=_PACKAGE_ATTR_ID,
        supplier_product_name_attr_id=_SUPPLIER_NAME_ATTR_ID,
    ).fetch_last_supply_procurement("2311")
    assert detail_hits == 0
    assert row == LastSupplyProcurementRow(
        catalog_code="2311",
        supplier_id=_AGENT_UUID,
        supplier_name="ООО Поставщик",
        last_buy_price=Decimal("12.5"),
        supply_moment=datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        package_quantity=Decimal("6"),
        supplier_product_name="Салат у поставщика",
    )


def test_fetch_last_supply_procurement_list_attrs_without_ids_skips_detail() -> None:
    # edge: attributes array present but our UUIDs absent → None, no detail
    detail_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_hits
        path = request.url.path
        if path.endswith(f"/entity/product/{_PRODUCT_UUID}"):
            detail_hits += 1
            return httpx.Response(500, json={"errors": [{"error": "no detail"}]})
        if path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "id": _PRODUCT_UUID,
                            "code": "2311",
                            "volume": 1,
                            "attributes": [{"id": "other", "value": 1}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1000},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(
        handler,
        package_quantity_attr_id=_PACKAGE_ATTR_ID,
        supplier_product_name_attr_id=_SUPPLIER_NAME_ATTR_ID,
    ).fetch_last_supply_procurement("2311")
    assert detail_hits == 0
    assert row is not None
    assert row.package_quantity is None
    assert row.supplier_product_name is None


def test_fetch_last_supply_procurement_missing_attributes_key_uses_detail() -> None:
    # edge: no attributes key on list → detail GET (existing miss path)
    detail_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_hits
        path = request.url.path
        if path.endswith(f"/entity/product/{_PRODUCT_UUID}"):
            detail_hits += 1
            return httpx.Response(
                200,
                json={
                    "id": _PRODUCT_UUID,
                    "attributes": [
                        {"id": _PACKAGE_ATTR_ID, "value": 4},
                        {"id": _SUPPLIER_NAME_ATTR_ID, "value": "Из detail"},
                    ],
                },
            )
        if path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "2311", "volume": 1}]},
            )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "moment": "2026-10-04 09:30:00.000",
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1000},
                            ],
                        },
                    },
                ],
            },
        )

    row = _client(
        handler,
        package_quantity_attr_id=_PACKAGE_ATTR_ID,
        supplier_product_name_attr_id=_SUPPLIER_NAME_ATTR_ID,
    ).fetch_last_supply_procurement("2311")
    assert detail_hits == 1
    assert row is not None
    assert row.package_quantity == Decimal("4")
    assert row.supplier_product_name == "Из detail"


def test_matrix_empty_supply_still_uses_price_zero() -> None:
    """Регрессия: matrix path не меняет семантику пустой приёмки."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 7}]},
            )
        return httpx.Response(200, json={"rows": []})

    result = _client(handler).fetch_purchase_attributes(frozenset({"SKU-1"}))
    assert result.attributes["SKU-1"].buy_price == "0"
