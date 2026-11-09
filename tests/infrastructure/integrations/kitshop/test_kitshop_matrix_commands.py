from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.http_client import KitShopApiClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)
from src.infrastructure.rate_limiting import SyncRateLimiter


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


def _transport(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def test_get_shops_keeps_product_base_template_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetShops")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Shops": [
                    {
                        "ShopId": 623161,
                        "ShopName": "PROBE микромаркет [799]",
                        "CompanyId": 109825,
                        "ProductBaseTemplateId": 7140,
                    },
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
    shops = client.get_shops()
    assert shops[0].product_base_template_id == 7140
    client.close()


def test_get_products_reads_is_deleted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Products": [
                    {
                        "ProductId": 167925,
                        "ProductName": "PROBE01",
                        "VendorCode": "PROBE01",
                        "IsDeleted": False,
                    },
                    {
                        "ProductId": 165454,
                        "ProductName": "PROBE01",
                        "VendorCode": "PROBE01",
                        "IsDeleted": True,
                    },
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
    products = client.get_products()
    assert products[0].is_deleted is False
    assert products[1].is_deleted is True
    client.close()


def test_add_command_body_has_shop_id_and_command_code_2() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        assert request.url.path.endswith("/AddCommand")
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client.add_command(shop_id=623161)
    body = seen["body"]
    assert isinstance(body, dict)
    command = body["Command"]
    assert command == {"ShopId": 623161, "CommandCode": 2}
    assert "DeviceId" not in command
    client.close()


def test_add_category_sends_priority_1() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        assert request.url.path.endswith("/AddCategoryToProductBaseTemplate")
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client.add_category_to_product_base_template(template_id=7140, category_id=6348)
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["TemplateId"] == 7140
    assert body["CategoryId"] == 6348
    assert body["Priority"] == 1
    client.close()


def test_remove_product_sends_template_and_product() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        assert request.url.path.endswith("/RemoveProductFromProductBaseTemplate")
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client.remove_product_from_product_base_template(template_id=7140, product_id=167925)
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["TemplateId"] == 7140
    assert body["ProductId"] == 167925
    client.close()


def test_add_product_sends_showcase_fields() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        assert request.url.path.endswith("/AddProductToProductBaseTemplate")
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client.add_product_to_product_base_template(
        template_id=7140,
        product_id=167925,
        price_rub=Decimal("151"),
        category_id=6348,
        location_id=20409,
    )
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["TemplateId"] == 7140
    assert body["ProductId"] == 167925
    assert body["Price"] == 151
    assert body["Disabled"] is False
    assert body["CategoryId"] == 6348
    assert body["LocationId"] == 20409
    assert "LocationAddress" not in body
    client.close()


def test_add_product_sends_disabled_true_from_argument() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ResultCode": 0})

    client = KitShopApiClient(
        account=_account(),
        settings=KitShopSettings(),
        http_client=_transport(handler),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        owns_http_client=True,
    )
    client.add_product_to_product_base_template(
        template_id=7140,
        product_id=167925,
        price_rub=Decimal("151"),
        category_id=6348,
        location_id=20409,
        disabled=True,
    )
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["Disabled"] is True
    client.close()


def test_get_product_base_template_reads_locations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/GetProductBaseTemplate")
        assert body["Id"] == 7140
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Locations": [
                    {"LocationId": 20408, "Name": "Open", "Type": 1},
                    {"LocationId": 20409, "Name": "Showcase", "Type": 2},
                ],
                "Categories": [{"CategoryId": 6348}],
                "Products": [
                    {
                        "ProductId": 167925,
                        "Price": 151,
                        "CategoryId": 6348,
                        "LocationId": 20409,
                        "Disabled": False,
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
    template = client.get_product_base_template(template_id=7140)
    assert len(template.locations) == 2
    assert template.locations[1].location_id == 20409
    assert template.locations[1].location_type == 2
    assert template.locations[1].name == "Showcase"
    assert template.categories[0].category_id == 6348
    assert template.products[0].product_id == 167925
    assert template.products[0].price == Decimal("151")
    assert template.products[0].category_id == 6348
    assert template.products[0].location_id == 20409
    assert template.products[0].disabled is False
    client.close()


@pytest.mark.parametrize(
    "groups_key",
    ("Groups", "ProductGroups"),
)
def test_get_product_groups_reads_group_id(groups_key: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetProductGroups")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                groups_key: [
                    {"GroupId": 6348, "GroupName": "PROBE group"},
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
    groups = client.get_product_groups()
    assert groups[0].group_id == 6348
    assert groups[0].group_name == "PROBE group"
    client.close()
