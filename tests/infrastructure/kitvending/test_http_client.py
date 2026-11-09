from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import pytest
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.config.kitvending import KitVendingSettings
from src.infrastructure.integrations.kitvending.api_models.enums import ResultCode
from src.infrastructure.integrations.kitvending.http_client import (
    KitVendingApiClient,
    KitVendingNetworkError,
    KitVendingResponseError,
)
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import KitVendingRequestIdStore
from src.infrastructure.rate_limiting import SyncGlobalBackoff, SyncRateLimiter


@dataclass(slots=True)
class StubRequestIdStore:
    next_value: int = 123456
    bump_calls: list[tuple[str, int]] = field(default_factory=list)
    next_calls: list[str] = field(default_factory=list)

    def next_id(self, *, login: str) -> int:
        self.next_calls.append(login)
        return self.next_value

    def bump_floor(self, *, login: str, floor: int) -> None:
        self.bump_calls.append((login, floor))
        self.next_value = max(self.next_value, floor) + 1


def _account() -> KitPlatformAccount:
    return make_platform_account(company_id=42, kit_company_id=42, login="user", password="pass")


def _transport_settings() -> KitVendingSettings:
    return KitVendingSettings.model_construct(
        api_base_url="https://kit.example/APIService.svc",
        backoff_seconds=0.01,
    )


def _client(
    handler: httpx.MockTransport,
    *,
    store: KitVendingRequestIdStore | None = None,
    backoff: SyncGlobalBackoff | None = None,
) -> KitVendingApiClient:
    return KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=httpx.Client(transport=handler),
        request_id_store=store or StubRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
        backoff=backoff,
    )


def test_invalid_request_id_enum_value() -> None:
    assert int(ResultCode.INVALID_REQUEST_ID) == 14


def test_next_request_id_uses_store_per_login() -> None:
    store = StubRequestIdStore(next_value=42)
    client = _client(
        httpx.MockTransport(lambda r: httpx.Response(200, json={"ResultCode": 0})),
        store=store,
    )

    assert client.next_request_id() == 42
    assert store.next_calls == ["user"]


def test_invalid_request_id_triggers_bump_and_retry() -> None:
    calls = 0
    store = StubRequestIdStore(next_value=100)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"ResultCode": ResultCode.INVALID_REQUEST_ID, "ErrorMessage": "bad id"},
            )
        return httpx.Response(200, json={"ResultCode": 0, "Sales": []})

    client = _client(httpx.MockTransport(handler), store=store)
    client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )

    assert calls == 2
    assert len(store.bump_calls) == 1
    assert store.bump_calls[0][0] == "user"


def test_invalid_request_id_after_too_many_request_retries_once() -> None:
    calls = 0
    store = StubRequestIdStore(next_value=100)
    result_codes = [
        ResultCode.TOO_MANY_REQUEST,
        ResultCode.INVALID_REQUEST_ID,
        ResultCode.SUCCESS,
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        result_code = result_codes[calls]
        calls += 1
        if result_code == ResultCode.SUCCESS:
            return httpx.Response(200, json={"ResultCode": result_code, "Sales": []})
        return httpx.Response(
            200,
            json={"ResultCode": result_code, "ErrorMessage": "retry"},
        )

    client = _client(
        httpx.MockTransport(handler),
        store=store,
        backoff=SyncGlobalBackoff(timeout=0.01),
    )
    client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )

    assert calls == 3
    assert len(store.bump_calls) == 1
    assert store.next_calls == ["user", "user", "user"]


def test_invalid_request_id_twice_raises() -> None:
    store = StubRequestIdStore(next_value=100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ResultCode": ResultCode.INVALID_REQUEST_ID, "ErrorMessage": "bad id"},
        )

    client = _client(httpx.MockTransport(handler), store=store)

    with pytest.raises(KitVendingResponseError, match="код ответа - 14"):
        client.get_goods_matrices()
    assert len(store.bump_calls) == 1


def test_build_auth_sign_md5() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ResultCode": 0, "Sales": []})

    client = _client(httpx.MockTransport(handler))
    client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )
    body = captured["body"]
    assert isinstance(body, dict)
    auth = body["Auth"]
    assert isinstance(auth, dict)
    expected = hashlib.md5(b"42pass123456").hexdigest()
    assert auth["Sign"] == expected
    assert auth["UserLogin"] == "user"


def test_public_build_auth_matches_md5_contract() -> None:
    client = _client(httpx.MockTransport(lambda r: httpx.Response(200, json={"ResultCode": 0})))
    auth = client.build_auth(123456)
    expected = hashlib.md5(b"42pass123456").hexdigest()
    assert auth == {
        "CompanyId": 42,
        "RequestId": 123456,
        "UserLogin": "user",
        "Sign": expected,
    }


def test_result_code_27_triggers_backoff_and_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"ResultCode": ResultCode.TOO_MANY_REQUEST})
        return httpx.Response(200, json={"ResultCode": 0, "Sales": []})

    client = _client(
        httpx.MockTransport(handler),
        backoff=SyncGlobalBackoff(timeout=0.01),
    )
    client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )
    assert calls == 2


def test_result_code_27_twice_raises_with_result_code() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ResultCode": ResultCode.TOO_MANY_REQUEST})

    client = _client(
        httpx.MockTransport(handler),
        backoff=SyncGlobalBackoff(timeout=0.01),
    )

    with pytest.raises(KitVendingResponseError, match="после 2 попыток") as exc_info:
        client.get_goods_matrices()

    assert exc_info.value.result_code == ResultCode.TOO_MANY_REQUEST
    assert calls == 2


def test_non_success_result_code_raises_without_bump() -> None:
    store = StubRequestIdStore(next_value=100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ResultCode": 5, "ErrorMessage": "fail"})

    client = _client(httpx.MockTransport(handler), store=store)

    with pytest.raises(KitVendingResponseError, match="код ответа - 5"):
        client.get_goods_matrices()
    assert store.bump_calls == []


def test_get_goods_matrices_parses_collection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "GoodsMatrices": [
                    {
                        "MatrixId": 1,
                        "MatrixName": "M",
                        "MatrixType": 1,
                        "Details": [],
                    }
                ],
            },
        )

    client = _client(httpx.MockTransport(handler))
    collection = client.get_goods_matrices()
    assert len(collection.items) == 1


def test_get_formulations_parses_recipes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Formulations": [{"FormulationId": 1, "FormulationName": "2301 | Latte"}],
            },
        )

    client = _client(httpx.MockTransport(handler))
    recipes = client.get_formulations()
    assert recipes[0].code == "2301"


def test_transport_retries_twice_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise httpx.ConnectTimeout("timeout")
        return httpx.Response(200, json={"ResultCode": 0, "Sales": []})

    client = _client(httpx.MockTransport(handler))
    client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )
    assert calls == 3


def test_transport_retries_503_then_succeeds() -> None:
    # happy
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ResultCode": 0, "Sales": []})

    client = _client(httpx.MockTransport(handler))
    sales = client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )
    assert sales == []
    assert calls["count"] == 2


def test_transport_retries_502_then_succeeds() -> None:
    # happy: тот же механизм для 502
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"ResultCode": 0, "Sales": []})

    client = _client(httpx.MockTransport(handler))
    client.get_sales(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
    )
    assert calls["count"] == 2


def test_transport_exhausted_503_raises_network_error() -> None:
    # error
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["count"] += 1
        return httpx.Response(503, text="unavailable")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KitVendingNetworkError):
        client.get_sales(
            from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
        )
    assert calls["count"] == 3


def test_transport_does_not_retry_http_400() -> None:
    # edge: 4xx не transport-retry
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["count"] += 1
        return httpx.Response(400, text="bad request")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KitVendingNetworkError):
        client.get_sales(
            from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
        )
    assert calls["count"] == 1


def test_network_error_raises_kit_vending_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KitVendingNetworkError):
        client.get_sales(
            from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            to_date=datetime(2026, 5, 2, 0, 0, tzinfo=UTC),
        )


def test_get_matrix_id_by_vm_id_builds_index_without_active_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url.path).endswith("/GetVendingMachines")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "VendingMachines": [
                    {
                        "VendingMachineId": 100,
                        "VendingMachineName": "Active [101]",
                        "GoodsMatrix": 55,
                    },
                    {
                        "VendingMachineId": 200,
                        "VendingMachineName": "Inactive [202] [ X ]",
                        "GoodsMatrix": {"Id": 66},
                    },
                    {
                        "VendingMachineId": 300,
                        "VendingMachineName": "No matrix [303]",
                        "GoodsMatrix": None,
                    },
                    {
                        "VendingMachineId": 400,
                        "VendingMachineName": "Zero [404]",
                        "GoodsMatrix": 0,
                    },
                ],
            },
        )

    client = _client(httpx.MockTransport(handler))
    assert client.get_matrix_id_by_vm_id() == {100: 55, 200: 66}


def test_get_matrix_id_by_vm_id_accepts_matrix_id_object_and_numeric_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "VendingMachines": [
                    {
                        "VendingMachineId": 1,
                        "VendingMachineName": "A [1]",
                        "GoodsMatrix": "88",
                    },
                    {
                        "VendingMachineId": 2,
                        "VendingMachineName": "B [2]",
                        "GoodsMatrix": {"MatrixId": 99},
                    },
                ],
            },
        )

    client = _client(httpx.MockTransport(handler))
    assert client.get_matrix_id_by_vm_id() == {1: 88, 2: 99}


def test_get_matrix_id_by_vm_id_propagates_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ResultCode": 27, "ErrorMessage": "fail"},
        )

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KitVendingResponseError):
        client.get_matrix_id_by_vm_id()
