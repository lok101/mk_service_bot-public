from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.application.inventory_reconciliation.kitvending import (
    HOLDING_SKIP_ALERT_SAMPLE_SIZE,
    KitSaleResolveSuccess,
)
from src.application.product_identity import (
    DomainProductResolve,
    ResolveHold,
    ResolveLegacy,
    ResolveRecognized,
)
from src.config.kitvending import KitVendingSettings
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


def _sale_2312() -> dict[str, Any]:
    return {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "2312 | X",
                "VendingMachine": 1002594,
                "VendingMachineName": "Кофе [176]",
                "MatrixId": None,
            }
        ],
    }


def _client_with_fixtures(
    *,
    sales_json: dict[str, Any],
    matrices_json: dict[str, Any],
    recipes_json: dict[str, Any],
    vm_json: dict[str, Any] | None = None,
    now: datetime = _FIXED_NOW,
    domain_product_identity_enabled: bool = False,
    resolve_sale_code: Callable[[str], DomainProductResolve] | None = None,
) -> KitVendingHttpClient:
    resolved_vm_json = vm_json if vm_json is not None else {"ResultCode": 0, "VendingMachines": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/GetSales"):
            return httpx.Response(200, json=sales_json)
        if path.endswith("/GetVendingMachines"):
            return httpx.Response(200, json=resolved_vm_json)
        if path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json=matrices_json)
        if path.endswith("/GetFormulations"):
            return httpx.Response(200, json=recipes_json)
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
        domain_product_identity_enabled=domain_product_identity_enabled,
        resolve_sale_code=resolve_sale_code,
    )


def test_critical_resolve_is_holding_skip() -> None:
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "без кода товара",
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
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert rows == []
    stats = client.last_fetch_stats
    assert stats.holding_skip_count == 1
    assert stats.fingerprint_pairs == (("176", "critical_product_resolve"),)
    assert stats.hold_at == datetime(2026, 5, 2, 7, 0, tzinfo=UTC)  # EKB→UTC
    assert stats.holding_samples[0].reason_class == "critical_product_resolve"


def test_no_machine_code_is_holding_skip() -> None:
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
    stats = client.last_fetch_stats
    assert stats.skipped_no_machine_code == 1
    assert stats.holding_skip_count == 1
    assert stats.fingerprint_pairs == (("kit_vm:1", "no_machine_code"),)


def test_non_critical_line_minus_one_not_holding() -> None:
    sales_json = {
        "ResultCode": 0,
        "Sales": [
            {
                "LineNumber": -1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 12:00:00",
                "GoodsName": "Товар 0",
                "VendingMachine": 1,
                "VendingMachineName": "Кофе [129]",
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
    stats = client.last_fetch_stats
    assert stats.holding_skip_count == 0
    assert stats.hold_at is None
    assert stats.fingerprint_pairs == ()
    assert stats.skipped_unresolved_product_non_holding >= 1


def test_fingerprint_includes_all_distinct_pairs() -> None:
    sales = []
    for i in range(1, 8):
        sales.append(
            {
                "LineNumber": 1,
                "Sum": 1.0,
                "DateTime": f"02.05.2026 12:0{i}:00",
                "GoodsName": "без кода товара",
                "VendingMachine": i,
                "VendingMachineName": f"Кофе [{100 + i}]",
                "MatrixId": None,
            }
        )
    client = _client_with_fixtures(
        sales_json={"ResultCode": 0, "Sales": sales},
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
    )
    client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    stats = client.last_fetch_stats
    assert stats.holding_skip_count == 7
    assert len(stats.fingerprint_pairs) == 7
    assert len(stats.holding_samples) == HOLDING_SKIP_ALERT_SAMPLE_SIZE


def test_vending_recognized_writes_catalog_code() -> None:
    def resolve(code: str) -> DomainProductResolve:
        assert code == "2312"
        return ResolveRecognized(domain_product_id="prod-1", catalog_code="9999")

    client = _client_with_fixtures(
        sales_json=_sale_2312(),
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        domain_product_identity_enabled=True,
        resolve_sale_code=resolve,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, tzinfo=UTC))
    assert rows[0].product_code == "9999"
    assert rows[0].domain_product_id == "prod-1"
    assert client.last_fetch_stats.holding_skip_count == 0
    client.fetch_raw_window(
        from_date=datetime(2026, 5, 1, tzinfo=UTC),
        to_date=datetime(2026, 5, 3, tzinfo=UTC),
    )
    source_id = next(iter(client._raw_sales_by_source_id))
    portion = client.resolve(source_id)
    assert isinstance(portion, KitSaleResolveSuccess)
    assert portion.row.product_code == "9999"
    assert portion.row.domain_product_id == "prod-1"


def test_vending_hold_clamps_with_critical_product_resolve() -> None:
    def resolve(code: str) -> DomainProductResolve:
        del code
        return ResolveHold(kind="hold_unknown_number")

    client = _client_with_fixtures(
        sales_json=_sale_2312(),
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        domain_product_identity_enabled=True,
        resolve_sale_code=resolve,
    )
    assert client.fetch_all(since=datetime(2026, 5, 1, tzinfo=UTC)) == []
    stats = client.last_fetch_stats
    assert stats.holding_skip_count == 1
    assert stats.hold_at is not None
    assert stats.holding_samples[0].reason_class == "critical_product_resolve"
    assert stats.holding_samples[0].detail == (
        "На карточке код доменного номера, а товара с таким номером нет."
    )


def test_vending_legacy_does_not_hold() -> None:
    def resolve(code: str) -> DomainProductResolve:
        return ResolveLegacy(code=code)

    client = _client_with_fixtures(
        sales_json=_sale_2312(),
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        domain_product_identity_enabled=True,
        resolve_sale_code=resolve,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, tzinfo=UTC))
    assert rows[0].product_code == "2312"
    assert rows[0].domain_product_id == ""
    assert client.last_fetch_stats.holding_skip_count == 0


def test_vending_flag_off_does_not_call_resolve() -> None:
    def resolve(code: str) -> DomainProductResolve:
        raise AssertionError(code)

    client = _client_with_fixtures(
        sales_json=_sale_2312(),
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        resolve_sale_code=resolve,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, tzinfo=UTC))
    assert rows[0].product_code == "2312"
