from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from src.config.moysklad import MoySkladSettings
from src.infrastructure.moysklad.purchase_prices.http_client import (
    MoySkladPurchasePricesHttpClient,
)
from src.infrastructure.rate_limiting import (
    SyncGlobalBackoff,
    SyncInFlightLimiter,
    SyncRateLimiter,
)


def _passthrough_gate(
    *,
    max_in_flight: int = 32,
) -> tuple[SyncRateLimiter, SyncGlobalBackoff, SyncInFlightLimiter]:
    return (
        SyncRateLimiter(max_requests=10_000, time_window=1.0),
        SyncGlobalBackoff(timeout=0.0),
        SyncInFlightLimiter(max_in_flight=max_in_flight),
    )


_STORE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_PRODUCT_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_fetch_uses_last_supply_price_not_buy_price() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "id": _PRODUCT_UUID,
                            "code": "SKU-1",
                            "buyPrice": {"value": 99999},  # must be ignored
                            "volume": 10,
                        },
                    ],
                },
            )
        if path.endswith("/entity/supply"):
            assert "order" in str(request.url) or "moment" in str(request.url)
            filt = str(request.url.params.get("filter", ""))
            assert _PRODUCT_UUID in filt
            assert _STORE_ID in filt
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "positions": {
                                "rows": [
                                    {
                                        "assortment": {"id": _PRODUCT_UUID},
                                        "price": 1250,
                                    },
                                ],
                            },
                        },
                    ],
                },
            )
        return httpx.Response(404, json={"errors": []})

    lim, bo, flight = _passthrough_gate()
    client = MoySkladPurchasePricesHttpClient(
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.moysklad.ru/api/remap/1.2",
        ),
        main_store_id=_STORE_ID,
        supply_fetch_concurrency=2,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    result = client.fetch_purchase_attributes(frozenset({"SKU-1"}))

    assert result.cards_found == 1
    assert result.attributes["SKU-1"].buy_price == "12.5"
    assert result.attributes["SKU-1"].volume == 10
    assert any(p.endswith("/entity/supply") for p in calls)


def _client(
    *, handler: object, concurrency: int = 1, attempts: int = 3
) -> MoySkladPurchasePricesHttpClient:
    lim, bo, flight = _passthrough_gate(max_in_flight=max(concurrency, 1))
    return MoySkladPurchasePricesHttpClient(
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
            base_url="https://api.moysklad.ru/api/remap/1.2",
        ),
        main_store_id=_STORE_ID,
        supply_fetch_concurrency=concurrency,
        request_attempts=attempts,
        retry_delay_seconds=0.0,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )


def test_empty_supply_sets_price_zero_keeps_volume() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 7}]},
            )
        if request.url.path.endswith("/entity/supply"):
            return httpx.Response(200, json={"rows": []})
        return httpx.Response(500)

    result = _client(handler=handler).fetch_purchase_attributes(frozenset({"SKU-1"}))
    assert result.cards_found == 1
    assert "SKU-1" in result.attributes
    assert result.attributes["SKU-1"].buy_price == "0"
    assert result.attributes["SKU-1"].volume == 7


def test_multiple_matching_positions_take_max_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 1}]},
            )
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "positions": {
                            "rows": [
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 1000},
                                {"assortment": {"id": _PRODUCT_UUID}, "price": 2500},
                                {"assortment": {"id": "other"}, "price": 99999},
                            ],
                        },
                    },
                ],
            },
        )

    result = _client(handler=handler).fetch_purchase_attributes(frozenset({"SKU-1"}))
    assert result.attributes["SKU-1"].buy_price == "25"


def test_supply_http_fail_omits_code_and_records_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 1},
                        {
                            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                            "code": "SKU-2",
                            "volume": 2,
                        },
                    ],
                },
            )
        filt = str(request.url.params.get("filter", ""))
        if _PRODUCT_UUID in filt:
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "positions": {
                                "rows": [
                                    {"assortment": {"id": _PRODUCT_UUID}, "price": 100},
                                ],
                            },
                        },
                    ],
                },
            )
        return httpx.Response(500, json={"errors": [{"error": "boom"}]})

    result = _client(handler=handler, concurrency=2, attempts=1).fetch_purchase_attributes(
        frozenset({"SKU-1", "SKU-2"}),
    )
    assert result.cards_found == 2
    assert "SKU-1" in result.attributes
    assert "SKU-2" not in result.attributes
    assert "SKU-2" in result.supply_http_failed


def test_empty_product_rows_cards_found_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/entity/product")
        return httpx.Response(200, json={"rows": []})

    result = _client(handler=handler).fetch_purchase_attributes(frozenset({"SKU-1"}))
    assert result.cards_found == 0
    assert result.attributes == {}


def test_supply_concurrency_respects_limit() -> None:
    import threading
    import time

    current = 0
    max_seen = 0
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal current, max_seen
        if request.url.path.endswith("/entity/product"):
            rows = [
                {
                    "id": f"00000000-0000-0000-0000-00000000000{i}",
                    "code": f"S{i}",
                    "volume": 1,
                }
                for i in range(5)
            ]
            return httpx.Response(200, json={"rows": rows})
        with lock:
            current += 1
            max_seen = max(max_seen, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return httpx.Response(200, json={"rows": []})

    _client(handler=handler, concurrency=2).fetch_purchase_attributes(
        frozenset({f"S{i}" for i in range(5)}),
    )
    assert max_seen <= 2


def test_fetch_logs_structured_counters(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entity/product"):
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 1}]},
            )
        return httpx.Response(200, json={"rows": []})

    with caplog.at_level(
        logging.INFO,
        logger="src.infrastructure.moysklad.purchase_prices.http_client",
    ):
        _client(handler=handler).fetch_purchase_attributes(frozenset({"SKU-1"}))

    matching = [
        record
        for record in caplog.records
        if record.getMessage() == "moysklad_purchase_attributes_fetched"
    ]
    assert len(matching) == 1
    record = matching[0]
    assert record.cards_found == 1
    assert record.supply_ok == 0
    assert record.supply_empty_price_zero == 1
    assert record.supply_http_failed == 0
    assert record.concurrency == 1
    assert record.store_id == _STORE_ID
    assert record.requested_count == 1


def test_from_settings_uses_short_network_retry_not_request_timeout() -> None:
    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        main_store_id=_STORE_ID,
        request_timeout_seconds=30,
        request_attempts=3,
        rate_limit_backoff_seconds=12.0,
        http_max_in_flight=2,
    )
    client = MoySkladPurchasePricesHttpClient.from_settings(
        settings,
        supply_fetch_concurrency=1,
    )
    try:
        assert client._retry_delay_seconds == 1.0
        assert client._retry_delay_seconds != float(settings.request_timeout_seconds)
        assert client._rate_limit_backoff_seconds == 12.0
        assert client._supply_fetch_concurrency == 1
    finally:
        client.close()


def test_from_settings_caps_concurrency_to_http_max_in_flight() -> None:
    # happy: ThreadPool workers never exceed Remap max in-flight
    settings = MoySkladSettings.model_construct(
        api_token=SecretStr("token"),
        main_store_id=_STORE_ID,
        http_max_in_flight=2,
    )
    client = MoySkladPurchasePricesHttpClient.from_settings(
        settings,
        supply_fetch_concurrency=7,
    )
    try:
        assert client._supply_fetch_concurrency == 2
    finally:
        client.close()


def test_get_retries_after_http_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith("/entity/product"):
            if calls["n"] == 1:
                return httpx.Response(
                    429,
                    json={"errors": [{"code": 1049, "error": "rate limit"}]},
                )
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 1}]},
            )
        return httpx.Response(200, json={"rows": []})

    lim, bo, flight = _passthrough_gate()
    client = MoySkladPurchasePricesHttpClient(
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.moysklad.ru/api/remap/1.2",
        ),
        main_store_id=_STORE_ID,
        supply_fetch_concurrency=1,
        request_attempts=3,
        retry_delay_seconds=0.0,
        rate_limit_backoff_seconds=0.0,
        rate_limiter=lim,
        backoff=bo,
        in_flight=flight,
    )
    result = client.fetch_purchase_attributes(frozenset({"SKU-1"}))
    assert result.cards_found == 1
    assert "SKU-1" in result.attributes
    assert calls["n"] >= 2


def test_get_retries_1073_without_tempo_backoff() -> None:
    # edge: parallel 1073 does not trigger SyncGlobalBackoff
    calls = {"n": 0}
    backoff = SyncGlobalBackoff(timeout=0.0)
    triggers = {"n": 0}
    original = backoff.trigger_backoff

    def counting_trigger(timeout: float | None = None) -> None:
        triggers["n"] += 1
        original(timeout)

    backoff.trigger_backoff = counting_trigger  # type: ignore[method-assign]

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith("/entity/product"):
            if calls["n"] == 1:
                return httpx.Response(
                    429,
                    json={"errors": [{"code": 1073, "error": "parallel"}]},
                )
            return httpx.Response(
                200,
                json={"rows": [{"id": _PRODUCT_UUID, "code": "SKU-1", "volume": 1}]},
            )
        return httpx.Response(200, json={"rows": []})

    lim, _, flight = _passthrough_gate()
    client = MoySkladPurchasePricesHttpClient(
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.moysklad.ru/api/remap/1.2",
        ),
        main_store_id=_STORE_ID,
        supply_fetch_concurrency=1,
        request_attempts=3,
        retry_delay_seconds=0.0,
        rate_limiter=lim,
        backoff=backoff,
        in_flight=flight,
    )
    result = client.fetch_purchase_attributes(frozenset({"SKU-1"}))
    assert result.cards_found == 1
    assert calls["n"] >= 2
    assert triggers["n"] == 0
