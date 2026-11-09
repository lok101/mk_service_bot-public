from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import SecretStr

from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.http_client import KitShopApiClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)
from src.infrastructure.rate_limiting import (
    KitShopApiPriority,
    PrioritySyncRateLimiter,
    SyncRateLimiter,
)


class _SpyPriorityLimiter(PrioritySyncRateLimiter):
    def __init__(self) -> None:
        super().__init__(max_requests=1000, time_window=1.0)
        self.priorities: list[KitShopApiPriority] = []

    def acquire(
        self,
        priority: KitShopApiPriority = KitShopApiPriority.LOW,
        *,
        timeout: float | None = None,
    ) -> None:
        _ = timeout
        self.priorities.append(priority)


_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "kitshop"


def _account() -> KitPlatformAccount:
    return KitPlatformAccount(
        account_key="shop1",
        company_id=1,
        platform=KitPlatform.KIT_SHOP,
        kit_company_id=42,
        role=KitPlatformRole.DEFAULT,
        login="shop_user",
        password=SecretStr("secret"),
    )


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_kitshop_client_get_sales_and_sale_by_id_from_fixtures() -> None:
    payloads = {
        "/GetSales": _load("sales_list.json"),
        "/GetSaleById": _load("sale_detail.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, body in payloads.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=body)
        raise AssertionError(request.url.path)

    api = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client = KitShopHttpClient(api=api, settings=KitShopSettings())
    sales = client.get_sales(
        from_date=datetime(2026, 9, 1, tzinfo=UTC),
        to_date=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].sale_id == 100
    detail = client.get_sale_by_id(sale_id=100)
    assert len(detail.positions) == 2
    api.close()


def test_facade_get_sale_by_id_acquires_low() -> None:
    # happy: sales path — acquire(low)
    spy = _SpyPriorityLimiter()
    payloads = {"/GetSaleById": _load("sale_detail.json")}

    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, body in payloads.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=body)
        raise AssertionError(request.url.path)

    api = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=spy,
        owns_http_client=True,
    )
    client = KitShopHttpClient(api=api, settings=KitShopSettings())
    client.get_sale_by_id(sale_id=100)
    assert spy.priorities
    assert all(p is KitShopApiPriority.LOW for p in spy.priorities)
    api.close()
