from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.application.inventory_reconciliation import KitSalePriceRow
from src.config.kitvending import KitVendingSettings
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.price_backfill_fetcher import (
    KitVendingMainApiPriceFetcher,
)
from src.infrastructure.rate_limiting import SyncRateLimiter


@dataclass(slots=True)
class _StubRequestIdStore:
    next_value: int = 1

    def next_id(self, *, login: str) -> int:
        return self.next_value

    def bump_floor(self, *, login: str, floor: int) -> None:
        self.next_value = max(self.next_value, floor)


def _account() -> KitPlatformAccount:
    return make_platform_account(company_id=42, kit_company_id=42, login="user", password="pass")


def _transport_settings() -> KitVendingSettings:
    return KitVendingSettings.model_construct(
        api_base_url="https://kit.example/APIService.svc",
        backoff_seconds=0.01,
    )


def _api_client(handler: httpx.MockTransport) -> KitVendingApiClient:
    return KitVendingApiClient(
        account=_account(),
        settings=_transport_settings(),
        http_client=httpx.Client(transport=handler),
        request_id_store=_StubRequestIdStore(),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )


def test_fetch_price_rows_calls_get_sales_with_window() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.path))
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Sales": [
                    {
                        "LineNumber": 2,
                        "Sum": 45.5,
                        "DateTime": "01.05.2026 12:00:00",
                        "GoodsName": "2312 | X",
                        "VendingMachine": 99,
                        "VendingMachineName": "[129]",
                        "MatrixId": 5,
                    },
                ],
            },
        )

    fetcher = KitVendingMainApiPriceFetcher(main_api=_api_client(httpx.MockTransport(handler)))
    from_date = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    to_date = datetime(2026, 7, 29, 8, 19, 54, tzinfo=UTC)

    rows = fetcher.fetch_price_rows(from_date=from_date, to_date=to_date)

    assert len(calls) == 1
    assert calls[0].endswith("/GetSales")
    assert rows == (KitSalePriceRow(source_id="kit:99:01.05.2026 12:00:00:2:5", sum_value=45.5),)
