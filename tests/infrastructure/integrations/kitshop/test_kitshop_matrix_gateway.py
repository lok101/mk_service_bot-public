from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.application.micromarket_loading import (
    CommandRejected,
    PreflightFailed,
    SnapshotStale,
    Synced,
)
from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.api_models.matrix import (
    KitShopMatrixCategory,
    KitShopMatrixLocation,
    KitShopMatrixTemplate,
    KitShopMatrixTemplateProduct,
    KitShopProductGroup,
)
from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.http_client import (
    KitShopApiClient,
    KitShopNetworkError,
    KitShopResponseError,
)
from src.infrastructure.integrations.kitshop.matrix_gateway import KitShopMatrixGateway
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)
from src.infrastructure.rate_limiting import KitShopApiPriority, PrioritySyncRateLimiter


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


class _Api:
    def __init__(
        self,
        *,
        location_type: int,
        template_category_ids: tuple[int, ...] = (),
        template_product_ids: tuple[int, ...] = (),
        command_error: bool = False,
        products: tuple[KitShopProduct, ...] | None = None,
    ) -> None:
        self.write_calls: list[object] = []
        self.template_reads = 0
        self._location_type = location_type
        self._template_category_ids = template_category_ids
        self._template_product_ids = template_product_ids
        self._command_error = command_error
        self.catalog_adds: list[tuple[str, str]] = []
        self.catalog_edits: list[tuple[int, str]] = []
        self.get_products_calls = 0
        self._next_catalog_id = 200001
        self._catalog_error: BaseException | None = None
        self._fail_add_vendor: str | None = None
        self._products = products

    def get_shops(self) -> tuple[KitShopShop, ...]:
        return (
            KitShopShop.model_validate(
                {
                    "ShopId": 623161,
                    "ShopName": "PROBE микромаркет [799]",
                    "CompanyId": 109825,
                    "ProductBaseTemplateId": 7140,
                },
            ),
        )

    def get_product_groups(self) -> tuple[KitShopProductGroup, ...]:
        return (KitShopProductGroup.model_validate({"GroupId": 6348, "GroupName": "probe-Салаты"}),)

    def get_products(self) -> tuple[KitShopProduct, ...]:
        self.get_products_calls += 1
        if self._products is not None:
            return self._products
        return (
            KitShopProduct.model_validate(
                {
                    "ProductId": 167925,
                    "ProductName": "PROBE01",
                    "VendorCode": "PROBE01",
                    "IsDeleted": False,
                },
            ),
        )

    def add_product(self, *, vendor_code: str, product_name: str) -> int:
        if self._catalog_error is not None:
            raise self._catalog_error
        if self._fail_add_vendor == vendor_code:
            raise KitShopNetworkError(f"write failed for {vendor_code}")
        self.catalog_adds.append((vendor_code, product_name))
        product_id = self._next_catalog_id
        self._next_catalog_id += 1
        new_card = KitShopProduct.model_validate(
            {
                "ProductId": product_id,
                "ProductName": product_name,
                "VendorCode": vendor_code,
                "IsDeleted": False,
            },
        )
        current = self.get_products()
        self.get_products_calls -= 1
        self._products = current + (new_card,)
        return product_id

    def edit_product_name(self, *, product_id: int, product_name: str) -> None:
        if self._catalog_error is not None:
            raise self._catalog_error
        self.catalog_edits.append((product_id, product_name))
        current = self.get_products()
        self.get_products_calls -= 1
        self._products = tuple(
            KitShopProduct.model_validate(
                {
                    "ProductId": item.product_id,
                    "ProductName": (
                        product_name if item.product_id == product_id else item.product_name
                    ),
                    "VendorCode": item.vendor_code,
                    "IsDeleted": item.is_deleted,
                },
            )
            for item in current
        )

    def get_product_base_template(self, *, template_id: int) -> KitShopMatrixTemplate:
        del template_id
        self.template_reads += 1
        return KitShopMatrixTemplate(
            locations=(
                KitShopMatrixLocation(
                    location_id=20409,
                    name="PROBE витрина",
                    location_type=self._location_type,
                ),
            ),
            categories=tuple(
                KitShopMatrixCategory(category_id=item) for item in self._template_category_ids
            ),
            products=tuple(
                KitShopMatrixTemplateProduct(
                    product_id=item,
                    price=Decimal("151"),
                    category_id=6348,
                    location_id=20409,
                    disabled=False,
                )
                for item in self._template_product_ids
            ),
        )

    def add_category_to_product_base_template(self, *, template_id: int, category_id: int) -> None:
        del template_id, category_id
        self.write_calls.append("category")

    def remove_product_from_product_base_template(
        self,
        *,
        template_id: int,
        product_id: int,
    ) -> None:
        del template_id, product_id
        self.write_calls.append("remove")

    def add_product_to_product_base_template(
        self,
        *,
        template_id: int,
        product_id: int,
        price_rub: Decimal,
        category_id: int,
        location_id: int,
        disabled: bool = False,
    ) -> None:
        del template_id, product_id, price_rub, category_id, location_id
        self.write_calls.append(("add", disabled))

    def add_command(self, *, shop_id: int) -> None:
        del shop_id
        self.write_calls.append("command")
        if self._command_error:
            raise KitShopResponseError("rejected", 1)


def test_gateway_preflight_error_does_not_write() -> None:
    api = _Api(location_type=1)
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, PreflightFailed)
    assert result.message == "Нужна одна витрина"
    assert api.write_calls == []


def test_gateway_adds_categories_then_removes_then_adds_then_commands() -> None:
    api = _Api(location_type=2, template_category_ids=(), template_product_ids=(167900,))
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, Synced)
    assert api.write_calls == ["category", "remove", ("add", False), "command"]


def test_gateway_stale_snapshot_skips_add_command() -> None:
    api = _Api(location_type=2, template_category_ids=(6348,), template_product_ids=())
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: False,
    )
    assert isinstance(result, SnapshotStale)
    assert api.write_calls == [("add", False)]


def test_gateway_command_rejected_does_not_rollback() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        command_error=True,
    )
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, CommandRejected)
    assert result.message == "База товаров на терминал не ушла"
    assert api.write_calls.count("remove") == 0
    assert api.write_calls[-1] == "command"


def test_gateway_empty_snapshot_removes_all_and_commands() -> None:
    api = _Api(location_type=2, template_category_ids=(6348,), template_product_ids=(167925,))
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, Synced)
    assert api.write_calls == ["remove", "command"]


def test_gateway_reads_product_base_template_once_on_success() -> None:
    api = _Api(location_type=2, template_category_ids=(), template_product_ids=(167900,))
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, Synced)
    assert api.template_reads == 1


def test_gateway_accepts_catalog_ensure_enabled_default_false() -> None:
    api = _Api(location_type=2, template_category_ids=(6348,), template_product_ids=())
    gateway = KitShopMatrixGateway(api=api, catalog_ensure_enabled=False)
    result = gateway.sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, Synced)
    assert api.catalog_adds == []
    assert api.catalog_edits == []
    assert api.get_products_calls == 1
    assert api.write_calls[-1] == "command"


def test_gateway_catalog_ensure_off_does_not_write_catalog() -> None:
    api = _Api(location_type=2, template_category_ids=(6348,), template_product_ids=())
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, Synced)
    assert api.catalog_adds == []
    assert api.catalog_edits == []
    assert api.get_products_calls == 1


def test_gateway_catalog_ensure_create_refetches_products_before_preflight() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(),
    )
    result = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True).sync_snapshot(
        machine_code="799",
        lines=(("d-1001", "151", 6348, False),),
        snapshot_still_current=lambda: True,
        catalog_names=(("d-1001", "Вода 0.5"),),
    )
    assert isinstance(result, Synced)
    assert api.catalog_adds == [("d-1001", "Вода 0.5")]
    assert api.catalog_edits == []
    assert api.get_products_calls == 2
    assert api.write_calls[-1] == "command"
    assert api.template_reads == 1


def test_gateway_catalog_ensure_rename_then_commands() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(
            KitShopProduct.model_validate(
                {
                    "ProductId": 167925,
                    "ProductName": "старое",
                    "VendorCode": "PROBE01",
                    "IsDeleted": False,
                },
            ),
        ),
    )
    result = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
        catalog_names=(("PROBE01", "Вода 0.5"),),
    )
    assert isinstance(result, Synced)
    assert api.catalog_adds == []
    assert api.catalog_edits == [(167925, "Вода 0.5")]
    assert api.get_products_calls == 2
    assert api.write_calls[-1] == "command"


def test_gateway_catalog_ensure_error_skips_template_and_command() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(
            KitShopProduct.model_validate(
                {
                    "ProductId": 1,
                    "ProductName": "A",
                    "VendorCode": "PROBE01",
                    "IsDeleted": False,
                },
            ),
            KitShopProduct.model_validate(
                {
                    "ProductId": 2,
                    "ProductName": "B",
                    "VendorCode": "PROBE01",
                    "IsDeleted": False,
                },
            ),
        ),
    )
    result = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
        catalog_names=(("PROBE01", "Вода 0.5"),),
    )
    assert isinstance(result, PreflightFailed)
    assert "PROBE01" in result.message
    assert api.catalog_adds == []
    assert api.catalog_edits == []
    assert api.write_calls == []
    assert api.template_reads == 0
    assert api.get_products_calls == 1


def test_gateway_catalog_ensure_empty_name_skips_template() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(),
    )
    result = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True).sync_snapshot(
        machine_code="799",
        lines=(("d-1001", "151", 6348, False),),
        snapshot_still_current=lambda: True,
        catalog_names=(("d-1001", "   "),),
    )
    assert isinstance(result, PreflightFailed)
    assert "d-1001" in result.message
    assert api.catalog_adds == []
    assert api.catalog_edits == []
    assert api.write_calls == []
    assert api.template_reads == 0


def test_gateway_catalog_ensure_response_error_is_reraised() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(),
    )
    api._catalog_error = KitShopResponseError("kit add failed", 9)
    gateway = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True)
    with pytest.raises(KitShopResponseError, match="kit add failed"):
        gateway.sync_snapshot(
            machine_code="799",
            lines=(("d-1001", "151", 6348, False),),
            snapshot_still_current=lambda: True,
            catalog_names=(("d-1001", "Вода 0.5"),),
        )
    assert api.write_calls == []
    assert api.template_reads == 0


def test_gateway_catalog_ensure_network_error_is_reraised() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(),
    )
    api._catalog_error = KitShopNetworkError("timeout")
    gateway = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True)
    with pytest.raises(KitShopNetworkError, match="timeout"):
        gateway.sync_snapshot(
            machine_code="799",
            lines=(("d-1001", "151", 6348, False),),
            snapshot_still_current=lambda: True,
            catalog_names=(("d-1001", "Вода 0.5"),),
        )
    assert api.write_calls == []
    assert api.template_reads == 0


def test_gateway_catalog_ensure_stops_before_template_after_prior_create() -> None:
    api = _Api(
        location_type=2,
        template_category_ids=(6348,),
        template_product_ids=(),
        products=(),
    )
    api._fail_add_vendor = "d-1002"
    gateway = KitShopMatrixGateway(api=api, catalog_ensure_enabled=True)
    with pytest.raises(KitShopNetworkError, match="d-1002"):
        gateway.sync_snapshot(
            machine_code="799",
            lines=(("d-1001", "151", 6348, False), ("d-1002", "151", 6348, False)),
            snapshot_still_current=lambda: True,
            catalog_names=(("d-1001", "Вода"), ("d-1002", "Сок")),
        )
    assert api.catalog_adds == [("d-1001", "Вода")]
    assert api.write_calls == []
    assert api.template_reads == 0


def test_gateway_sync_snapshot_acquires_high_on_all_http() -> None:
    # happy: publish Protocol-path (ensure/matrix/command) → acquire(high)
    spy = _SpyPriorityLimiter()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/GetShops"):
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
                        }
                    ],
                },
            )
        if path.endswith("/GetProductGroups"):
            return httpx.Response(
                200,
                json={
                    "ResultCode": 0,
                    "ProductGroups": [{"GroupId": 6348, "GroupName": "probe-Салаты"}],
                },
            )
        if path.endswith("/GetProducts"):
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
                        }
                    ],
                },
            )
        if path.endswith("/GetProductBaseTemplate"):
            return httpx.Response(
                200,
                json={
                    "ResultCode": 0,
                    "Locations": [
                        {"LocationId": 1, "Name": "vitrine", "Type": 2},
                    ],
                    "Categories": [{"CategoryId": 6348}],
                    "Products": [],
                },
            )
        if path.endswith("/AddProductToProductBaseTemplate"):
            return httpx.Response(200, json={"ResultCode": 0})
        if path.endswith("/AddCommand"):
            return httpx.Response(200, json={"ResultCode": 0})
        raise AssertionError(path)

    api = KitShopApiClient(
        account=KitPlatformAccount(
            account_key="shop1",
            company_id=1,
            platform=KitPlatform.KIT_SHOP,
            kit_company_id=42,
            role=KitPlatformRole.DEFAULT,
            login="shop_user",
            password=SecretStr("secret"),
        ),
        settings=KitShopSettings(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        rate_limiter=spy,
        owns_http_client=True,
    )
    result = KitShopMatrixGateway(api=api).sync_snapshot(
        machine_code="799",
        lines=(("PROBE01", "151", 6348, False),),
        snapshot_still_current=lambda: True,
    )
    assert isinstance(result, Synced)
    assert spy.priorities
    assert all(p is KitShopApiPriority.HIGH for p in spy.priorities)
    api.close()
