from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, cast

import httpx
from beartype import beartype

from src.config.kitvending import KitVendingSettings
from src.infrastructure.integrations.kitvending.api_models.enums import ResultCode
from src.infrastructure.integrations.kitvending.api_models.matrix import MatricesKitCollection
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel
from src.infrastructure.integrations.kitvending.datetime_kit import KitDateTime
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import KitVendingRequestIdStore
from src.infrastructure.integrations.kitvending.vm_current_matrix import normalize_goods_matrix_id
from src.infrastructure.rate_limiting import SyncGlobalBackoff, SyncRateLimiter

_LOGGER = logging.getLogger(__name__)


class KitVendingResponseError(Exception):
    def __init__(self, message: str, result_code: int) -> None:
        self.result_code = result_code
        super().__init__(message)


class KitVendingNetworkError(Exception):
    pass


_TRANSPORT_RETRY_ATTEMPTS: Final = 3
_TRANSPORT_RETRY_STATUS_CODES: Final = frozenset({502, 503, 504})


@beartype
class KitVendingApiClient:
    def __init__(
        self,
        *,
        account: KitPlatformAccount,
        settings: KitVendingSettings,
        http_client: httpx.Client,
        request_id_store: KitVendingRequestIdStore,
        rate_limiter: SyncRateLimiter,
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
    ) -> list[SaleModel]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetSales"
        from_dt_api_format = KitDateTime.datetime_to_str_kit(from_date)
        to_dt_api_format = KitDateTime.datetime_to_str_kit(to_date)

        def build_data() -> dict[str, Any]:
            return {
                "Auth": self.build_auth(self.next_request_id()),
                "Filter": {
                    "UpDate": from_dt_api_format,
                    "ToDate": to_dt_api_format,
                },
            }

        response = self.send_post(url, build_data)
        return [SaleModel.model_validate(item) for item in response["Sales"]]

    @beartype
    def get_goods_matrices(self) -> MatricesKitCollection:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetGoodsMatrices"

        def build_data() -> dict[str, Any]:
            return {"Auth": self.build_auth(self.next_request_id())}

        response = self.send_post(url, build_data)
        return MatricesKitCollection.model_validate(response)

    @beartype
    def get_formulations(self) -> list[RecipeModel]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetFormulations"

        def build_data() -> dict[str, Any]:
            return {"Auth": self.build_auth(self.next_request_id())}

        response = self.send_post(url, build_data)
        return [RecipeModel.model_validate(item) for item in response["Formulations"]]

    @beartype
    def get_matrix_id_by_vm_id(self) -> dict[int, int]:
        url = f"{self._settings.api_base_url.rstrip('/')}/GetVendingMachines"

        def build_data() -> dict[str, Any]:
            return {"Auth": self.build_auth(self.next_request_id())}

        response = self.send_post(url, build_data)
        machines = response["VendingMachines"]
        index: dict[int, int] = {}
        for item in machines:
            vm_id = int(item["VendingMachineId"])
            matrix_id = normalize_goods_matrix_id(item.get("GoodsMatrix"))
            if matrix_id is not None:
                index[vm_id] = matrix_id
        return index

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
    ) -> dict[str, Any]:
        request_id_recovery_used = False
        too_many_request_retry_used = False

        while True:
            self._backoff.wait_if_blocked()
            self._rate_limiter.acquire()
            data = build_data()

            try:
                for transport_attempt in range(1, _TRANSPORT_RETRY_ATTEMPTS + 1):
                    try:
                        response = self._http_client.post(url, content=json.dumps(data))
                        response.raise_for_status()
                        break
                    except (
                        httpx.TimeoutException,
                        httpx.ConnectError,
                        httpx.NetworkError,
                    ) as exc:
                        if transport_attempt == _TRANSPORT_RETRY_ATTEMPTS:
                            raise KitVendingNetworkError(f"Ошибка сети: {exc}") from exc
                        time.sleep(self._settings.backoff_seconds)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code not in _TRANSPORT_RETRY_STATUS_CODES:
                            raise
                        if transport_attempt == _TRANSPORT_RETRY_ATTEMPTS:
                            raise KitVendingNetworkError(f"Ошибка сети: {exc}") from exc
                        time.sleep(self._settings.backoff_seconds)
                else:
                    raise KitVendingNetworkError("Неожиданное завершение transport retry")
            except httpx.HTTPError as exc:
                raise KitVendingNetworkError(f"Ошибка сети: {exc}") from exc

            try:
                response_data = cast(dict[str, Any], response.json())
            except json.JSONDecodeError as exc:
                raise KitVendingResponseError(
                    f"Не удалось разобрать JSON ответ от API: {exc}",
                    result_code=-1,
                ) from exc

            try:
                result_code = int(response_data["ResultCode"])
            except KeyError as exc:
                raise KitVendingResponseError(
                    "Ответ API не содержит поле ResultCode",
                    result_code=-1,
                ) from exc

            if result_code == ResultCode.INVALID_REQUEST_ID:
                if request_id_recovery_used:
                    message = response_data.get("ErrorMessage", "Неизвестная ошибка")
                    raise KitVendingResponseError(
                        f"Не удалось получить данные от Kit API, код ответа - {result_code}, "
                        f"текст ошибки: {message}",
                        result_code=result_code,
                    )
                _LOGGER.warning(
                    "kitvending_request_id_recovered",
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

            if result_code == ResultCode.TOO_MANY_REQUEST:
                if not too_many_request_retry_used:
                    self._backoff.trigger_backoff()
                    too_many_request_retry_used = True
                    continue
                raise KitVendingResponseError(
                    "Превышен лимит запросов к API после 2 попыток",
                    result_code=result_code,
                )

            if result_code != ResultCode.SUCCESS:
                message = response_data.get("ErrorMessage", "Неизвестная ошибка")
                raise KitVendingResponseError(
                    f"Не удалось получить данные от Kit API, код ответа - {result_code}, "
                    f"текст ошибки: {message}",
                    result_code=result_code,
                )

            return response_data

    @beartype
    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()
