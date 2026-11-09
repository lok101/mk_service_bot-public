from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.application.master_data.companies import KitPlatformRole
from src.application.master_data.company_directory import KitCompanyDirectory
from src.config.kitvending import KitVendingSettings
from src.infrastructure.integrations.kitvending.api_models.matrix import GoodsMatrixModel
from src.infrastructure.integrations.kitvending.catalog_cache import CatalogCache
from src.infrastructure.integrations.kitvending.catalog_merge import fetch_merged_catalog
from src.infrastructure.integrations.kitvending.client import KitVendingHttpClient
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.rate_limiting import SyncRateLimiter

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "kitvending"
_FIXED_NOW = datetime(2026, 5, 3, 0, 0, tzinfo=UTC)


@dataclass(slots=True)
class StubRequestIdStore:
    next_value: int

    def next_id(self, *, login: str) -> int:
        return self.next_value

    def bump_floor(self, *, login: str, floor: int) -> None:
        self.next_value = max(self.next_value, floor)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _account() -> KitPlatformAccount:
    return make_platform_account(company_id=42, kit_company_id=42, login="user", password="pass")


def _transport_settings() -> KitVendingSettings:
    return KitVendingSettings.model_construct(
        api_base_url="https://kit.example/APIService.svc",
        backoff_seconds=0.01,
        catalog_cache_ttl_seconds=3600,
    )


def _client_with_fixtures(
    *,
    sales_json: dict[str, Any],
    matrices_json: dict[str, Any] | None = None,
    recipes_json: dict[str, Any] | None = None,
    vm_json: dict[str, Any] | None = None,
    now: datetime = _FIXED_NOW,
    company_directory: KitCompanyDirectory | None = None,
) -> KitVendingHttpClient:
    resolved_matrices = (
        matrices_json if matrices_json is not None else load_fixture("get_goods_matrices.json")
    )
    resolved_recipes = (
        recipes_json if recipes_json is not None else load_fixture("get_formulations.json")
    )
    resolved_vm_json = vm_json if vm_json is not None else {"ResultCode": 0, "VendingMachines": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/GetSales"):
            return httpx.Response(200, json=sales_json)
        if path.endswith("/GetVendingMachines"):
            return httpx.Response(200, json=resolved_vm_json)
        if path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json=resolved_matrices)
        if path.endswith("/GetFormulations"):
            return httpx.Response(200, json=resolved_recipes)
        return httpx.Response(404, json={"ResultCode": 404})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    api = KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=123456),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    catalog_cache = CatalogCache(ttl_seconds=3600, now=lambda: 1000.0)
    return KitVendingHttpClient(
        main_api=api,
        catalog_clients=(api,),
        catalog_fetch=lambda: fetch_merged_catalog((api,)),
        catalog_cache=catalog_cache,
        shared_http_client=http,
        now=lambda: now,
        company_directory=company_directory,
    )


def test_fetch_all_bulk_get_sales_returns_kit_vending_sale_rows() -> None:
    client = _client_with_fixtures(
        sales_json=load_fixture("get_sales.json"),
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
    )
    since = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    rows = client.fetch_all(since=since)
    assert len(rows) == 2
    assert rows[0].vending_machine_code == "129"
    assert rows[0].product_code == "2312"
    assert rows[0].quantity == Decimal("1")
    assert rows[0].occurred_at.tzinfo == UTC
    assert rows[0].sale_kind == "coffee"
    by_code = {row.vending_machine_code: row for row in rows}
    assert by_code["501"].product_code == "2311"
    assert by_code["501"].sale_kind == "snack"


def test_fetch_all_maps_kit_sum_to_row_price() -> None:
    client = _client_with_fixtures(
        sales_json={
            "ResultCode": 0,
            "Sales": [
                {
                    "LineNumber": 1,
                    "Sum": 150.5,
                    "DateTime": "02.05.2026 12:00:00",
                    "GoodsName": "2312 | Cap",
                    "VendingMachine": 99,
                    "VendingMachineName": "Кофе [129]",
                    "MatrixId": None,
                }
            ],
        },
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
    )

    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))

    assert len(rows) == 1
    assert rows[0].price == Decimal("150.5")


def test_fetch_all_updates_last_fetch_stats_on_mutable_client() -> None:
    client = _client_with_fixtures(
        sales_json={
            "ResultCode": 0,
            "Sales": [
                {
                    "LineNumber": 1,
                    "Sum": 1.0,
                    "DateTime": "02.05.2026 12:00:00",
                    "GoodsName": "без кода",
                    "VendingMachine": 1,
                    "VendingMachineName": "[129]",
                    "MatrixId": None,
                }
            ],
        },
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
    )
    client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert client.last_fetch_stats.skipped_unresolved_product == 1


def test_fetch_all_tracks_skip_stats_for_unresolved_product_and_missing_machine_code() -> None:
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "без кода",
                "VendingMachine": 1,
                "VendingMachineName": "[129]",
                "MatrixId": None,
            },
            {
                "LineNumber": 2,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "2312 | X",
                "VendingMachine": 2,
                "VendingMachineName": "без кода",
                "MatrixId": None,
            },
        ],
    }
    client = _client_with_fixtures(
        sales_json=sales_json,
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
    )
    since = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)

    rows = client.fetch_all(since=since)
    stats = client.last_fetch_stats

    assert rows == []
    assert stats.skipped_unresolved_product == 1
    assert stats.skipped_no_machine_code == 1


def test_fetch_all_logs_space_after_period_for_missing_machine_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "2312 | X",
                "VendingMachine": 1,
                "VendingMachineName": "без кода",
                "MatrixId": None,
            }
        ],
    }
    client = _client_with_fixtures(
        sales_json=sales_json,
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
    )
    client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))

    assert any("для продажи. vending_machine_name=" in record.message for record in caplog.records)


def test_fetch_all_makes_only_four_http_calls_on_cold_cache() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        path = request.url.path
        if path.endswith("/GetSales"):
            return httpx.Response(200, json=load_fixture("get_sales.json"))
        if path.endswith("/GetVendingMachines"):
            return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": []})
        if path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json=load_fixture("get_goods_matrices.json"))
        if path.endswith("/GetFormulations"):
            return httpx.Response(200, json=load_fixture("get_formulations.json"))
        return httpx.Response(404, json={"ResultCode": 404})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    api = KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=123456),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    client = KitVendingHttpClient(
        main_api=api,
        catalog_clients=(api,),
        catalog_fetch=lambda: fetch_merged_catalog((api,)),
        catalog_cache=CatalogCache(ttl_seconds=3600, now=lambda: 1000.0),
        shared_http_client=http,
        now=lambda: _FIXED_NOW,
    )
    since = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    client.fetch_all(since=since)
    assert calls == 4


def test_fetch_all_reuses_catalog_cache_on_second_fetch() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        path = request.url.path
        if path.endswith("/GetSales"):
            return httpx.Response(200, json=load_fixture("get_sales.json"))
        if path.endswith("/GetVendingMachines"):
            return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": []})
        if path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json=load_fixture("get_goods_matrices.json"))
        if path.endswith("/GetFormulations"):
            return httpx.Response(200, json=load_fixture("get_formulations.json"))
        return httpx.Response(404, json={"ResultCode": 404})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    api = KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=123456),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    client = KitVendingHttpClient(
        main_api=api,
        catalog_clients=(api,),
        catalog_fetch=lambda: fetch_merged_catalog((api,)),
        catalog_cache=CatalogCache(ttl_seconds=3600, now=lambda: 1000.0),
        shared_http_client=http,
        now=lambda: _FIXED_NOW,
    )
    since = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    client.fetch_all(since=since)
    calls_after_first = calls
    client.fetch_all(since=since)
    assert calls - calls_after_first == 2  # GetSales + fresh GetVendingMachines


def test_fetch_all_uses_child_matrix_for_resolve() -> None:
    """Продажа с matrix_id только в каталоге дочернего аккаунта."""
    child_matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 77,
            "MatrixName": "Child",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 3,
                    "Price2": 10.0,
                    "GoodsName": "2312 | Coffee",
                    "MaxCount": 5,
                }
            ],
        }
    )
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 3,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "Товар 2312",
                "VendingMachine": 1,
                "VendingMachineName": "Кофе [129]",
                "MatrixId": 77,
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/GetSales"):
            return httpx.Response(200, json=sales_json)
        if path.endswith("/GetVendingMachines"):
            return httpx.Response(
                200,
                json={
                    "ResultCode": 0,
                    "VendingMachines": [
                        {
                            "VendingMachineId": 1,
                            "VendingMachineName": "Кофе [129]",
                            "GoodsMatrix": 77,
                        }
                    ],
                },
            )
        return httpx.Response(404, json={"ResultCode": 404})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    main_api = KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=123456),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    client = KitVendingHttpClient(
        main_api=main_api,
        catalog_fetch=lambda: {"matrices": {77: child_matrix}, "recipes": {}},
        catalog_cache=CatalogCache(ttl_seconds=3600, now=lambda: 1000.0),
        now=lambda: _FIXED_NOW,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0].product_code == "2312"


def test_fetch_all_get_sales_only_from_main_account_catalog_from_all() -> None:
    logins_by_endpoint: dict[str, list[str]] = {
        "GetSales": [],
        "GetVendingMachines": [],
        "GetGoodsMatrices": [],
        "GetFormulations": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        login = body["Auth"]["UserLogin"]
        endpoint = request.url.path.rsplit("/", 1)[-1]
        logins_by_endpoint[endpoint].append(login)
        if endpoint == "GetSales":
            return httpx.Response(200, json={"ResultCode": 0, "Sales": []})
        if endpoint == "GetVendingMachines":
            return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": []})
        if endpoint == "GetGoodsMatrices":
            return httpx.Response(200, json={"ResultCode": 0, "GoodsMatrices": []})
        return httpx.Response(200, json={"ResultCode": 0, "Formulations": []})

    settings = KitVendingSettings.model_construct(
        api_base_url="https://kit.example/APIService.svc",
        backoff_seconds=0.01,
        catalog_cache_ttl_seconds=3600,
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    head = make_platform_account(
        account_key="head",
        company_id=1,
        kit_company_id=1,
        login="head",
        password="p1",
        role=KitPlatformRole.SALES_POLL,
    )
    child = make_platform_account(
        account_key="child",
        company_id=2,
        kit_company_id=2,
        login="child",
        password="p2",
        role=KitPlatformRole.CATALOG,
    )
    limiter = SyncRateLimiter(max_requests=100, time_window=1.0)
    main_api = KitVendingApiClient(
        account=head,
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=1),
        rate_limiter=limiter,
    )
    child_api = KitVendingApiClient(
        account=child,
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=2),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    client = KitVendingHttpClient(
        main_api=main_api,
        catalog_clients=(main_api, child_api),
        catalog_fetch=lambda: fetch_merged_catalog((main_api, child_api)),
        catalog_cache=CatalogCache(ttl_seconds=3600, now=lambda: 1000.0),
        shared_http_client=http,
    )
    client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))

    assert logins_by_endpoint["GetSales"] == ["head"]
    assert logins_by_endpoint["GetVendingMachines"] == ["head"]
    assert sorted(logins_by_endpoint["GetGoodsMatrices"]) == ["child", "head"]
    assert sorted(logins_by_endpoint["GetFormulations"]) == ["child", "head"]
    client.close()


def test_fetch_all_calls_get_vending_machines_every_poll() -> None:
    calls = {"vm": 0, "matrices": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/GetSales"):
            return httpx.Response(200, json={"ResultCode": 0, "Sales": []})
        if path.endswith("/GetVendingMachines"):
            calls["vm"] += 1
            return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": []})
        if path.endswith("/GetGoodsMatrices"):
            calls["matrices"] += 1
            return httpx.Response(200, json=load_fixture("get_goods_matrices.json"))
        if path.endswith("/GetFormulations"):
            return httpx.Response(200, json=load_fixture("get_formulations.json"))
        return httpx.Response(404, json={"ResultCode": 404})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    api = KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=123456),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    catalog_cache = CatalogCache(ttl_seconds=3600, now=lambda: 1000.0)
    client = KitVendingHttpClient(
        main_api=api,
        catalog_clients=(api,),
        catalog_fetch=lambda: fetch_merged_catalog((api,)),
        catalog_cache=catalog_cache,
        shared_http_client=http,
        now=lambda: _FIXED_NOW,
    )
    since = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    client.fetch_all(since=since)
    client.fetch_all(since=since)
    assert calls["vm"] == 2
    assert calls["matrices"] == 1  # catalog TTL hit на втором poll


def test_fetch_all_resolves_human_name_via_vm_current_matrix() -> None:
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "Капучино классический",
                "VendingMachine": 1002594,
                "VendingMachineName": "Кофе [176]",
                "MatrixId": 1,
            }
        ],
    }
    matrices_json = {
        "ResultCode": 0,
        "GoodsMatrices": [
            {
                "MatrixId": 55,
                "MatrixName": "Coffee",
                "MatrixType": 1,
                "Details": [
                    {
                        "LineNumber": 1,
                        "Price2": 50.0,
                        "GoodsName": "2301 | Cap",
                        "MaxCount": 10,
                    }
                ],
            }
        ],
    }
    vm_json = {
        "ResultCode": 0,
        "VendingMachines": [
            {
                "VendingMachineId": 1002594,
                "VendingMachineName": "Кофе [176]",
                "GoodsMatrix": 55,
            }
        ],
    }
    client = _client_with_fixtures(
        sales_json=sales_json,
        matrices_json=matrices_json,
        recipes_json=load_fixture("get_formulations.json"),
        vm_json=vm_json,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0].product_code == "2301"
    assert rows[0].vending_machine_code == "176"


def test_critical_resolve_warning_includes_vm_current_matrix_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "Капучино классический",
                "VendingMachine": 1002594,
                "VendingMachineName": "Кофе [176]",
                "MatrixId": None,
            }
        ],
    }
    client = _client_with_fixtures(
        sales_json=sales_json,
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        vm_json={"ResultCode": 0, "VendingMachines": []},
    )
    client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    records = [r for r in caplog.records if "код товара" in r.getMessage()]
    assert records
    # structured extras (LoggerAdapter / logger.warning(..., extra=...))
    assert getattr(records[0], "resolved_via", None) == "vm_current_matrix"
    assert getattr(records[0], "vending_machine_id", None) == 1002594


def test_fetch_all_uses_until_as_to_date_when_provided() -> None:
    captured_to_date: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/GetSales"):
            body = json.loads(request.content)
            captured_to_date.append(body["Filter"]["ToDate"])
            return httpx.Response(200, json={"ResultCode": 0, "Sales": []})
        if request.url.path.endswith("/GetVendingMachines"):
            return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": []})
        if request.url.path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json={"ResultCode": 0, "GoodsMatrices": []})
        return httpx.Response(200, json={"ResultCode": 0, "Formulations": []})

    settings = _transport_settings()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    main_api = KitVendingApiClient(
        account=_account(),
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=1),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    client = KitVendingHttpClient(
        main_api=main_api,
        catalog_clients=(main_api,),
        catalog_fetch=lambda: fetch_merged_catalog((main_api,)),
        catalog_cache=CatalogCache(ttl_seconds=3600, now=lambda: 1000.0),
        shared_http_client=http,
        now=lambda: datetime(2026, 8, 12, 0, 0, tzinfo=UTC),
    )

    until = datetime(2026, 8, 5, 15, 30, tzinfo=UTC)
    client.fetch_all(since=datetime(2026, 8, 1, 0, 0, tzinfo=UTC), until=until)

    # KitDateTime.datetime_to_str_kit конвертирует в Asia/Yekaterinburg (UTC+5)
    assert captured_to_date == ["05.08.2026 20:30:00"]
    client.close()


def test_fetch_all_defaults_to_date_to_now_when_until_omitted() -> None:
    captured_to_date: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/GetSales"):
            body = json.loads(request.content)
            captured_to_date.append(body["Filter"]["ToDate"])
            return httpx.Response(200, json={"ResultCode": 0, "Sales": []})
        if request.url.path.endswith("/GetVendingMachines"):
            return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": []})
        if request.url.path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json={"ResultCode": 0, "GoodsMatrices": []})
        return httpx.Response(200, json={"ResultCode": 0, "Formulations": []})

    settings = _transport_settings()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    main_api = KitVendingApiClient(
        account=_account(),
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=1),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )
    client = KitVendingHttpClient(
        main_api=main_api,
        catalog_clients=(main_api,),
        catalog_fetch=lambda: fetch_merged_catalog((main_api,)),
        catalog_cache=CatalogCache(ttl_seconds=3600, now=lambda: 1000.0),
        shared_http_client=http,
        now=lambda: datetime(2026, 8, 12, 0, 0, tzinfo=UTC),
    )

    client.fetch_all(since=datetime(2026, 8, 1, 0, 0, tzinfo=UTC))

    # now=2026-08-12T00:00:00Z → Asia/Yekaterinburg (UTC+5) = 05:00:00
    assert captured_to_date == ["12.08.2026 05:00:00"]
    client.close()
