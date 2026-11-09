from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.infrastructure.integrations.moysklad.assortments import AssortmentRef
from src.infrastructure.micromarket_loading.ms_warehouse_stock import (
    MoySkladWarehouseStockFetcher,
)

_WAREHOUSE = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_PRODUCT = UUID("11111111-2222-3333-4444-555555555555")


class _FakeClient:
    def __init__(self) -> None:
        self.resolve_calls: list[list[str]] = []

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        return []

    async def post_entity(
        self,
        *,
        entity_path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return {}

    async def delete_entity(self, *, entity_path: str, entity_id: str) -> None:
        return None

    async def get_store_id_by_code(self, code: str) -> UUID:
        return _WAREHOUSE

    async def get_inventory_list(
        self,
        *,
        store_id: UUID,
        moment_from: datetime | None,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        return []

    async def get_inventory_positions(self, *, inventory_id: str) -> list[Mapping[str, Any]]:
        return []

    async def get_move_list(
        self,
        *,
        moment_from: datetime,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        return []

    async def get_move_positions(
        self,
        *,
        move_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        return []

    async def get_moves_by_ids(
        self,
        *,
        move_ids: tuple[str, ...],
    ) -> list[Mapping[str, Any]]:
        return []

    async def get_store_code_by_id(self, store_id: UUID) -> str:
        return "store"

    async def aclose(self) -> None:
        return None

    async def get_stock_report_bystore(
        self,
        *,
        store_id: UUID,
    ) -> list[dict[str, Any]]:
        assert store_id == _WAREHOUSE
        return [
            {
                "code": "SKU-A",
                "meta": {
                    "href": f"https://api.moysklad.ru/api/remap/1.2/entity/product/{_PRODUCT}",
                },
                "stockByStore": [
                    {
                        "meta": {
                            "href": f"https://api.moysklad.ru/api/remap/1.2/entity/store/{_WAREHOUSE}"
                        },
                        "stock": 5,
                    },
                ],
            },
        ]

    async def resolve_assortments_by_codes(
        self,
        codes: list[str],
    ) -> dict[str, AssortmentRef]:
        self.resolve_calls.append(list(codes))
        return {code: AssortmentRef(id=_PRODUCT, entity_type="product") for code in codes}


def test_fetch_uses_row_code_without_resolve_when_all_codes_in_report() -> None:
    client = _FakeClient()
    fetcher = MoySkladWarehouseStockFetcher(client=client, main_warehouse_id=_WAREHOUSE)
    qty = fetcher.fetch_qty_by_catalog_codes(["SKU-A"])
    assert qty["SKU-A"] == Decimal("5")
    assert client.resolve_calls == []


def test_fetch_resolves_only_missing_codes() -> None:
    client = _FakeClient()
    fetcher = MoySkladWarehouseStockFetcher(client=client, main_warehouse_id=_WAREHOUSE)
    qty = fetcher.fetch_qty_by_catalog_codes(["SKU-A", "SKU-MISSING"])
    assert qty["SKU-A"] == Decimal("5")
    assert client.resolve_calls == [["SKU-MISSING"]]


def test_fetch_empty_codes_skips_ms() -> None:
    class _NoCallClient(_FakeClient):
        async def get_stock_report_bystore(
            self,
            *,
            store_id: UUID,
        ) -> list[dict[str, Any]]:
            raise AssertionError("should not call MS")

    fetcher = MoySkladWarehouseStockFetcher(client=_NoCallClient(), main_warehouse_id=_WAREHOUSE)
    assert fetcher.fetch_qty_by_catalog_codes([]) == {}
