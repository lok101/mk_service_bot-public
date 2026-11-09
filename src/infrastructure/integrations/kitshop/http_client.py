from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, cast

import httpx
from beartype import beartype

from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.api_models.enums import ResultCode
from src.infrastructure.integrations.kitshop.api_models.matrix import (
    KitShopMatrixTemplate,
    KitShopProductGroup,
)
from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.sale import KitShopSale
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.parsing.datetime_kit import format_kit_datetime
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import KitVendingRequestIdStore
from src.infrastructure.rate_limiting import (
    KitShopApiPriority,
    PrioritySyncRateLimiter,
    SyncGlobalBackoff,
    SyncRateLimiter,
    current_kitshop_api_priority,
)

_LOGGER = logging.getLogger(__name__)
_TRANSPORT_RETRY_ATTEMPTS: Final = 3


def _numeric_retry_after_seconds(raw: str | None) -> float | None:
    """Parse numeric Retry-After seconds; HTTP-date / invalid → None."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _json_price(price_rub: Decimal) -> int | float:
    if price_rub == price_rub.to_integral_value():
        return int(price_rub)
    return float(price_rub)


class KitShopResponseError(Exception):
    def __init__(self, message: str, result_code: int) -> None:
        self.result_code = result_code
        super().__init__(message)


class KitShopNetworkError(Exception):
    pass


@beartype
def _sale_payload_from_get_sale_by_id(response: dict[str, Any]) -> dict[str, Any]:
    """Extract sale object from GetSaleById (live: ``Sales[0]``; fixtures may use ``Sale``)."""
    sales = response.get("Sales")
    if isinstance(sales, list) and sales:
        first = sales[0]
        if isinstance(first, dict):
            return first
    sale = response.get("Sale")
    if isinstance(sale, dict):
        return sale
    raise KitShopResponseError(
        "Ответ GetSaleById не содержит Sales[0] / Sale",
        result_code=int(response.get("ResultCode", -1)),
    )


@beartype
class KitShopApiClient:
    def __init__(
        self,
        *,
        account: KitPlatformAccount,
        settings: KitShopSettings,
        http_client: httpx.Client,
        request_id_store: KitVendingRequestIdStore,
        rate_limiter: SyncRateLimiter | PrioritySyncRateLimiter,
        backoff: SyncGlobalBackoff | None = None,
        owns_http_client: bool = False,
    ) -> None:
        self.account = account
        self._settings = settings
        self._http_client = http_client
        self._request_id_store = request_id_store
        self._rate_limiter = rate_limiter
        self._backoff = backoff or SyncGlobalBackoff(timeout=settings.backoff_seconds)
        self._owns_http_client = owns_http_client

    @beartype
    def get_sales(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
        priority: KitShopApiPriority | None = None,
    ) -> list[KitShopSale]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetSales"
        from_dt = format_kit_datetime(from_date)
        to_dt = format_kit_datetime(to_date)

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "Filter": {
                    "UpDate": from_dt,
                    "ToDate": to_dt,
                },
            }

        response = self.send_post(url, build_data, priority=priority)
        return [KitShopSale.model_validate(item) for item in response["Sales"]]

    @beartype
    def get_sale_by_id(
        self,
        *,
        sale_id: int,
        priority: KitShopApiPriority | None = None,
    ) -> KitShopSale:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetSaleById"

        def build_data() -> dict[str, Any]:
            # PDF Kit Shop API v1.3: request field is ``Id``, not ``SaleId``.
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "Id": sale_id,
            }

        response = self.send_post(url, build_data, priority=priority)
        return KitShopSale.model_validate(_sale_payload_from_get_sale_by_id(response))

    @beartype
    def get_shops(self) -> list[KitShopShop]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetShops"

        def build_data() -> dict[str, Any]:
            return {"Auth": self.build_auth(self.next_request_id())}

        response = self.send_post(url, build_data)
        return [KitShopShop.model_validate(item) for item in response["Shops"]]

    @beartype
    def get_shop_by_id(self, *, shop_id: int) -> KitShopShop:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetShopById"

        def build_data() -> dict[str, Any]:
            # PDF Kit Shop API v1.3: request field is ``Id``, not ``ShopId``.
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "Id": shop_id,
            }

        response = self.send_post(url, build_data)
        return KitShopShop.model_validate(response["Shop"])

    @beartype
    def get_products(self) -> list[KitShopProduct]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetProducts"

        def build_data() -> dict[str, Any]:
            return {"Auth": self.build_auth(self.next_request_id())}

        response = self.send_post(url, build_data)
        return [KitShopProduct.model_validate(item) for item in response["Products"]]

    @beartype
    def get_product_groups(
        self,
        *,
        acquire_timeout: float | None = None,
    ) -> list[KitShopProductGroup]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetProductGroups"

        def build_data() -> dict[str, Any]:
            return {"Auth": self.build_auth(self.next_request_id())}

        response = self.send_post(url, build_data, acquire_timeout=acquire_timeout)
        raw_groups = response.get("ProductGroups")
        if not isinstance(raw_groups, list):
            raw_groups = response.get("Groups")
        if not isinstance(raw_groups, list):
            raise KitShopResponseError(
                "Ответ GetProductGroups не содержит ProductGroups / Groups",
                result_code=int(response.get("ResultCode", -1)),
            )
        return [KitShopProductGroup.model_validate(item) for item in raw_groups]

    @beartype
    def get_product_base_template(self, *, template_id: int) -> KitShopMatrixTemplate:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetProductBaseTemplate"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "Id": template_id,
            }

        response = self.send_post(url, build_data)
        return KitShopMatrixTemplate.model_validate(response)

    @beartype
    def add_category_to_product_base_template(
        self,
        *,
        template_id: int,
        category_id: int,
    ) -> None:
        url = f"{self._settings.api_base_url.rstrip('/')}/AddCategoryToProductBaseTemplate"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "TemplateId": template_id,
                "CategoryId": category_id,
                "Priority": 1,
            }

        self.send_post(url, build_data)

    @beartype
    def remove_product_from_product_base_template(
        self,
        *,
        template_id: int,
        product_id: int,
    ) -> None:
        url = f"{self._settings.api_base_url.rstrip('/')}/RemoveProductFromProductBaseTemplate"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "TemplateId": template_id,
                "ProductId": product_id,
            }

        self.send_post(url, build_data)

    @beartype
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
        url = f"{self._settings.api_base_url.rstrip('/')}/AddProductToProductBaseTemplate"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "TemplateId": template_id,
                "ProductId": product_id,
                "Price": _json_price(price_rub),
                "Disabled": disabled,
                "CategoryId": category_id,
                "LocationId": location_id,
            }

        self.send_post(url, build_data)

    @beartype
    def add_product(self, *, vendor_code: str, product_name: str) -> int:
        url = f"{self._settings.api_base_url.rstrip('/')}/AddProduct"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "ProductName": product_name,
                "UnitType": 1,
                "TaxType": 2,
                "AccuracyType": 1,
                "AccuracyValue": 2,
                "VendorCode": vendor_code,
            }

        response = self.send_post(url, build_data)
        try:
            return int(response["Id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KitShopResponseError(
                "Ответ AddProduct не содержит Id",
                result_code=int(response.get("ResultCode", -1)),
            ) from exc

    @beartype
    def edit_product_name(self, *, product_id: int, product_name: str) -> None:
        url = f"{self._settings.api_base_url.rstrip('/')}/EditProduct"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "ProductId": product_id,
                "ProductName": product_name,
            }

        self.send_post(url, build_data)

    @beartype
    def add_command(self, *, shop_id: int) -> None:
        url = f"{self._settings.api_base_url.rstrip('/')}/AddCommand"

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "Command": {
                    "ShopId": shop_id,
                    "CommandCode": 2,
                },
            }

        self.send_post(url, build_data)

    @beartype
    def next_request_id(self) -> int:
        return self._request_id_store.next_id(login=self.account.login)

    @beartype
    def build_auth(self, request_id: int) -> dict[str, Any]:
        password = self.account.password.get_secret_value()
        kit_company_id = self.account.kit_company_id
        sign = hashlib.md5(f"{kit_company_id}{password}{request_id}".encode()).hexdigest()
        return {
            "CompanyId": kit_company_id,
            "RequestId": request_id,
            "UserLogin": self.account.login,
            "Sign": sign,
        }

    @beartype
    def send_post(
        self,
        url: str,
        build_data: Callable[[], dict[str, Any]],
        *,
        priority: KitShopApiPriority | None = None,
        acquire_timeout: float | None = None,
    ) -> dict[str, Any]:
        request_id_recovery_used = False
        http_429_retry_used = False
        http_attempt = 0
        effective_priority = priority if priority is not None else current_kitshop_api_priority()
        path = url.rsplit("/", maxsplit=1)[-1]

        while True:
            self._backoff.wait_if_blocked()
            acquire_started = time.perf_counter()
            self._rate_limiter.acquire(priority=effective_priority, timeout=acquire_timeout)
            rate_limit_wait_seconds = round(time.perf_counter() - acquire_started, 3)
            data = build_data()
            http_attempt += 1

            try:
                for transport_attempt in range(1, _TRANSPORT_RETRY_ATTEMPTS + 1):
                    try:
                        response = self._http_client.post(url, content=json.dumps(data))
                        if response.status_code == 429:
                            retry_after = _numeric_retry_after_seconds(
                                response.headers.get("Retry-After")
                            )
                            backoff_seconds = (
                                retry_after
                                if retry_after is not None
                                else float(self._settings.backoff_seconds)
                            )
                            _LOGGER.warning(
                                "kitshop_http_rate_limited",
                                extra={
                                    "path": path,
                                    "retry": http_429_retry_used,
                                    "backoff_seconds": backoff_seconds,
                                    "retry_after_present": retry_after is not None,
                                },
                            )
                            self._backoff.trigger_backoff(timeout=backoff_seconds)
                            if http_429_retry_used:
                                raise KitShopNetworkError(
                                    "HTTP 429 после повторной попытки",
                                )
                            http_429_retry_used = True
                            break
                        response.raise_for_status()
                        break
                    except (
                        httpx.TimeoutException,
                        httpx.ConnectError,
                        httpx.NetworkError,
                    ) as exc:
                        if transport_attempt == _TRANSPORT_RETRY_ATTEMPTS:
                            raise KitShopNetworkError(f"Ошибка сети: {exc}") from exc
                        time.sleep(self._settings.backoff_seconds)
                else:
                    raise KitShopNetworkError("Неожиданное завершение transport retry")
            except KitShopNetworkError:
                raise
            except httpx.HTTPError as exc:
                raise KitShopNetworkError(f"Ошибка сети: {exc}") from exc

            if response.status_code == 429:
                continue

            try:
                response_data = cast(dict[str, Any], response.json())
            except json.JSONDecodeError as exc:
                raise KitShopResponseError(
                    f"Не удалось разобрать JSON ответ от API: {exc}",
                    result_code=-1,
                ) from exc

            try:
                result_code = int(response_data["ResultCode"])
            except KeyError as exc:
                raise KitShopResponseError(
                    "Ответ API не содержит поле ResultCode",
                    result_code=-1,
                ) from exc

            if result_code == ResultCode.INVALID_REQUEST_ID:
                if request_id_recovery_used:
                    message = response_data.get("ErrorMessage", "Неизвестная ошибка")
                    raise KitShopResponseError(
                        f"Не удалось получить данные от Kit Shop API, код ответа - {result_code}, "
                        f"текст ошибки: {message}",
                        result_code=result_code,
                    )
                _LOGGER.warning(
                    "kitshop_request_id_recovered",
                    extra={
                        "login": self.account.login,
                        "result_code": int(ResultCode.INVALID_REQUEST_ID),
                        "retry": True,
                    },
                )
                self._request_id_store.bump_floor(
                    login=self.account.login,
                    floor=int(time.time() * 1000),
                )
                request_id_recovery_used = True
                continue

            if result_code != ResultCode.SUCCESS:
                message = response_data.get("ErrorMessage", "Неизвестная ошибка")
                raise KitShopResponseError(
                    f"Не удалось получить данные от Kit Shop API, код ответа - {result_code}, "
                    f"текст ошибки: {message}",
                    result_code=result_code,
                )

            _LOGGER.info(
                "kitshop_http_request",
                extra={
                    "path": path,
                    "result_code": result_code,
                    "priority": effective_priority.value,
                    "rate_limit_wait_seconds": rate_limit_wait_seconds,
                    "http_attempt": http_attempt,
                },
            )
            return response_data

    @beartype
    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()
