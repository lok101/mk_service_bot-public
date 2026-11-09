from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip
from src.config.kitvending import KitVendingSettings
from src.domain.ids import MachineId
from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel
from src.infrastructure.integrations.kitvending.catalog_cache import CatalogCache
from src.infrastructure.integrations.kitvending.catalog_merge import fetch_merged_catalog
from src.infrastructure.integrations.kitvending.client import KitVendingHttpClient
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.source_id import build_sale_source_id
from src.infrastructure.rate_limiting import SyncRateLimiter
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.machine_sales_skipped_fakes import InMemoryMachineSaleSkipStore
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

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


def _client_with_fixtures(
    *,
    sales_json: dict[str, Any],
    matrices_json: dict[str, Any],
    recipes_json: dict[str, Any],
    skip_store: InMemoryMachineSaleSkipStore | None = None,
    vm_json: dict[str, Any] | None = None,
    now: datetime = _FIXED_NOW,
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
        skip_store=skip_store,
    )


def test_poll_path_writes_skip_on_holding_and_non_holding() -> None:
    skip_store = InMemoryMachineSaleSkipStore()
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
            },
            {
                "LineNumber": -1,
                "Sum": 1.0,
                "DateTime": "02.05.2026 13:00:00",
                "GoodsName": "переплата",
                "VendingMachine": 99,
                "VendingMachineName": "Кофе [129]",
                "MatrixId": 5,
            },
        ],
    }
    client = _client_with_fixtures(
        sales_json=sales_json,
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        skip_store=skip_store,
    )

    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))

    assert rows == []
    holding_sale = SaleModel.model_validate(sales_json["Sales"][0])
    non_holding_sale = SaleModel.model_validate(sales_json["Sales"][1])
    holding_id = build_sale_source_id(holding_sale)
    non_holding_id = build_sale_source_id(non_holding_sale)
    holding_skip = skip_store.get(holding_id)
    non_holding_skip = skip_store.get(non_holding_id)
    assert holding_skip is not None
    assert holding_skip.reason_class == "critical_product_resolve"
    assert non_holding_skip is not None
    assert non_holding_skip.reason_class == "line_neg_1"


def test_successful_import_clears_skip() -> None:
    skip_store = InMemoryMachineSaleSkipStore()
    sales_store = InMemoryMachineSalesStore()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    skip_store.upsert(
        MachineSaleSkip(
            source_id="kv-1",
            reason_class="critical_product_resolve",
            kit_vending_machine_id=1,
            vending_machine_name="VM01",
            occurred_at=now,
            line_number=1,
            matrix_id=None,
            goods_name="x",
            external_id=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
    )
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-05T12:00:00Z",
            },
        ],
    )
    service = ImportKitVendingSales(
        sales_store=sales_store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
        skip_store=skip_store,
    )

    result = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert result.inserted == 1
    assert skip_store.get("kv-1") is None


def test_portion_resolve_loads_catalog_once_per_raw_window() -> None:
    client = _client_with_fixtures(
        sales_json=load_fixture("get_sales.json"),
        matrices_json=load_fixture("get_goods_matrices.json"),
        recipes_json=load_fixture("get_formulations.json"),
        vm_json={
            "ResultCode": 0,
            "VendingMachines": [
                {
                    "VendingMachineId": 99,
                    "VendingMachineName": "Кофе [129]",
                    "GoodsMatrix": 5,
                },
                {
                    "VendingMachineId": 50,
                    "VendingMachineName": "Snacks [501]",
                    "GoodsMatrix": 1,
                },
            ],
        },
    )
    load_calls = 0
    matrix_map_calls = 0
    original_load = client.catalog_cache.load
    original_matrix_map = client.main_api.get_matrix_id_by_vm_id

    def counting_load(fetch: object) -> object:
        nonlocal load_calls
        load_calls += 1
        return original_load(fetch)  # type: ignore[arg-type]

    def counting_matrix_map() -> dict[int, int]:
        nonlocal matrix_map_calls
        matrix_map_calls += 1
        return original_matrix_map()

    client.catalog_cache.load = counting_load  # type: ignore[method-assign]
    client.main_api.get_matrix_id_by_vm_id = counting_matrix_map  # type: ignore[method-assign]

    identities = client.fetch_raw_window(
        from_date=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
    )
    assert len(identities) >= 2
    for identity in identities:
        client.resolve(identity.source_id)

    assert load_calls <= 1
    assert matrix_map_calls <= 1
