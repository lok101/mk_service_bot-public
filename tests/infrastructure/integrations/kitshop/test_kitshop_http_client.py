from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.api_models.enums import ResultCode
from src.infrastructure.integrations.kitshop.http_client import (
    KitShopApiClient,
    KitShopNetworkError,
    KitShopResponseError,
)
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


def _idle_http() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ResultCode": 0})

    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def _transport(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def test_kitshop_build_auth_sign() -> None:
    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_idle_http(),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    auth = client.build_auth(12345)
    expected = hashlib.md5(b"42secret12345").hexdigest()
    assert auth == {
        "CompanyId": 42,
        "RequestId": 12345,
        "UserLogin": "shop_user",
        "Sign": expected,
    }
    client.close()


def test_kitshop_rate_limiter_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.infrastructure.rate_limiting as rl

    settings = KitShopSettings()
    ticks = [100.0, 100.0, 100.0, 100.0 + settings.window_seconds]

    def fake_monotonic() -> float:
        return ticks.pop(0) if ticks else 100.0 + settings.window_seconds

    slept: list[float] = []
    monkeypatch.setattr(rl.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(rl.time, "sleep", lambda s: slept.append(s))

    limiter = SyncRateLimiter(
        max_requests=settings.requests_per_window,
        time_window=settings.window_seconds,
    )
    limiter.acquire()
    limiter.acquire()
    assert slept and slept[0] == pytest.approx(settings.window_seconds, abs=0.01)


def test_kitshop_api_get_sales_parses_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetSales")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Sales": [
                    {
                        "SaleId": 100,
                        "CompanyId": 1,
                        "ShopId": 10,
                        "DeviceId": 99,
                        "SaleDateTime": "04.09.2026 12:00:00",
                        "Positions": [],
                    }
                ],
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    sales = client.get_sales(
        from_date=datetime(2026, 9, 4, tzinfo=UTC),
        to_date=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].sale_id == 100
    client.close()


def test_kitshop_api_get_sale_by_id_with_positions() -> None:
    """Live GetSaleById: request ``Id``, response ``Sales`` list (PDF + prod)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetSaleById")
        data = json.loads(request.content)
        assert data["Id"] == 100
        assert "SaleId" not in data
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Sales": [
                    {
                        "SaleId": 100,
                        "CompanyId": 1,
                        "ShopId": 10,
                        "DeviceId": 99,
                        "SaleDateTime": "04.09.2026 12:00:00",
                        "Positions": [
                            {
                                "PositionId": 1,
                                "ProductId": 50,
                                "Quantity": 2.0,
                                "Price": 100.0,
                            }
                        ],
                    }
                ],
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    sale = client.get_sale_by_id(sale_id=100)
    assert sale.sale_id == 100
    assert len(sale.positions) == 1
    assert sale.positions[0].product_id == 50
    client.close()


def test_kitshop_api_get_sale_by_id_accepts_singular_sale() -> None:
    """Fixture / older shape: singular ``Sale`` still parses."""

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["Id"] == 200
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Sale": {
                    "SaleId": 200,
                    "CompanyId": 1,
                    "ShopId": 10,
                    "DeviceId": 99,
                    "SaleDateTime": "04.09.2026 12:00:00",
                    "Positions": [],
                },
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    sale = client.get_sale_by_id(sale_id=200)
    assert sale.sale_id == 200
    client.close()


def test_kitshop_api_get_shop_by_id_sends_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetShopById")
        data = json.loads(request.content)
        assert data["Id"] == 10
        assert "ShopId" not in data
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Shop": {"ShopId": 10, "ShopName": "Офис [701]", "CompanyId": 1},
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    shop = client.get_shop_by_id(shop_id=10)
    assert shop.shop_id == 10
    client.close()


def test_kitshop_api_get_shops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetShops")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Shops": [{"ShopId": 10, "ShopName": "Офис [701]", "CompanyId": 1}],
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    shops = client.get_shops()
    assert shops[0].shop_name == "Офис [701]"
    client.close()


def test_kitshop_api_get_products() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetProducts")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Products": [{"ProductId": 50, "ProductName": "Snack", "VendorCode": "2311"}],
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    products = client.get_products()
    assert products[0].vendor_code == "2311"
    client.close()


def test_kitshop_invalid_request_id_retries() -> None:
    """ResultCode INVALID_REQUEST_ID (14) → bump RequestId + один retry (зеркало Vending)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"ResultCode": int(ResultCode.INVALID_REQUEST_ID)})
        return httpx.Response(200, json={"ResultCode": 0, "Shops": []})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(backoff_seconds=0.01),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    assert client.get_shops() == []
    assert calls["n"] == 2
    client.close()


def test_add_product_sends_pdf_constants_without_price_and_group() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/AddProduct")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ResultCode": 0, "Id": 20})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    product_id = client.add_product(vendor_code="d-1001", product_name="Вода 0.5")
    assert product_id == 20
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["VendorCode"] == "d-1001"
    assert body["ProductName"] == "Вода 0.5"
    assert body["UnitType"] == 1
    assert body["TaxType"] == 2
    assert body["AccuracyType"] == 1
    assert body["AccuracyValue"] == 2
    assert "Price" not in body
    assert "GroupId" not in body
    assert "Auth" in body
    client.close()


def test_add_product_result_code_error_is_kitshop_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ResultCode": 9, "ErrorMessage": "ошибка AddProduct"},
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    with pytest.raises(KitShopResponseError, match="ошибка AddProduct"):
        client.add_product(vendor_code="d-1", product_name="X")
    client.close()


def test_add_product_network_error_is_kitshop_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(backoff_seconds=0.01),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    with pytest.raises(KitShopNetworkError):
        client.add_product(vendor_code="d-1", product_name="X")
    client.close()


def test_edit_product_name_sends_only_product_id_and_name() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/EditProduct")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client.edit_product_name(product_id=20, product_name="Вода 0.5л")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["ProductId"] == 20
    assert body["ProductName"] == "Вода 0.5л"
    assert set(body.keys()) == {"Auth", "ProductId", "ProductName"}
    client.close()


def test_edit_product_name_result_code_error_is_kitshop_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ResultCode": 9, "ErrorMessage": "ошибка EditProduct"},
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    with pytest.raises(KitShopResponseError, match="ошибка EditProduct"):
        client.edit_product_name(product_id=20, product_name="X")
    client.close()


def test_send_post_passes_explicit_priority_to_limiter() -> None:
    # happy: send_post прокидывает priority в acquire
    spy = _SpyPriorityLimiter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=spy,
        owns_http_client=True,
    )
    client.send_post(
        "https://example.test/Ping",
        lambda: {"Auth": client.build_auth(client.next_request_id())},
        priority=KitShopApiPriority.HIGH,
    )
    assert spy.priorities == [KitShopApiPriority.HIGH]
    client.close()


def test_send_post_default_priority_is_low() -> None:
    # edge: default без priority = low
    spy = _SpyPriorityLimiter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=spy,
        owns_http_client=True,
    )
    client.send_post(
        "https://example.test/Ping",
        lambda: {"Auth": client.build_auth(client.next_request_id())},
    )
    assert spy.priorities == [KitShopApiPriority.LOW]
    client.close()


def test_http_429_retries_once_with_numeric_retry_after() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return httpx.Response(200, json={"ResultCode": 0, "Shops": []})

    spy = _SpyPriorityLimiter()
    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(backoff_seconds=1.0),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=spy,
        owns_http_client=True,
    )
    shops = client.get_shops()
    assert shops == []
    assert calls["n"] == 2
    assert len(spy.priorities) == 2
    client.close()


def test_http_429_second_attempt_raises_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.01"})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(backoff_seconds=0.01),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    with pytest.raises(KitShopNetworkError, match="429"):
        client.get_shops()
    client.close()


def test_result_code_27_does_not_backoff_or_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "ResultCode": int(ResultCode.FISCAL_SIGN_NOT_NUMERIC),
                "ErrorMessage": "FiscalSign",
            },
        )

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(backoff_seconds=0.01),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    with pytest.raises(KitShopResponseError) as exc_info:
        client.get_shops()
    assert exc_info.value.result_code == int(ResultCode.FISCAL_SIGN_NOT_NUMERIC)
    assert calls["n"] == 1
    client.close()
