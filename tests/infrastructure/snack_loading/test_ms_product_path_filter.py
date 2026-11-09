from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from src.infrastructure.integrations.moysklad.assortments import AssortmentRef
from src.infrastructure.snack_loading.ms_loading import load_product_id_to_code


class _FilterCaptureClient:
    def __init__(self) -> None:
        self.filter_exprs: list[str] = []

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        del entity_path, limit, offset
        self.filter_exprs.append(filter_expr)
        return [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "code": "SKU1",
            }
        ]

    async def post_entity(
        self,
        *,
        entity_path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del entity_path, body
        return {}

    async def delete_entity(self, *, entity_path: str, entity_id: str) -> None:
        del entity_path, entity_id

    async def get_store_id_by_code(self, code: str) -> UUID:
        del code
        return UUID("00000000-0000-0000-0000-000000000001")

    async def resolve_assortments_by_codes(self, codes: list[str]) -> dict[str, AssortmentRef]:
        del codes
        return {}

    async def get_stock_report_bystore(
        self,
        *,
        store_id: UUID,
    ) -> list[Mapping[str, Any]]:
        del store_id
        return []

    async def get_inventory_list(
        self,
        *,
        store_id: UUID,
        moment_from: datetime | None,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        del store_id, moment_from, moment_to
        return []

    async def get_inventory_positions(
        self,
        *,
        inventory_id: str,
    ) -> list[Mapping[str, Any]]:
        del inventory_id
        return []

    async def get_move_list(
        self,
        *,
        moment_from: datetime,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        del moment_from, moment_to
        return []

    async def get_move_positions(
        self,
        *,
        move_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        del move_id, limit, offset
        return []

    async def get_moves_by_ids(
        self,
        *,
        move_ids: tuple[str, ...],
    ) -> list[Mapping[str, Any]]:
        del move_ids
        return []

    async def get_store_code_by_id(self, store_id: UUID) -> str:
        del store_id
        return "x"

    async def aclose(self) -> None:
        return None


def test_load_product_id_to_code_uses_prefix_filter_when_recursive() -> None:
    client = _FilterCaptureClient()
    result = asyncio.run(
        load_product_id_to_code(
            client,
            products_path="Основной склад/СНЕК",
            recursive=True,
        )
    )
    assert client.filter_exprs == ["pathName~=Основной склад/СНЕК"]
    assert result[UUID("11111111-1111-1111-1111-111111111111")] == "SKU1"


def test_load_product_id_to_code_uses_exact_path_when_not_recursive() -> None:
    client = _FilterCaptureClient()
    asyncio.run(
        load_product_id_to_code(
            client,
            products_path="Основной склад/СНЕК",
            recursive=False,
        )
    )
    assert client.filter_exprs == ["pathName=Основной склад/СНЕК"]


class _PaginatedProductClient(_FilterCaptureClient):
    def __init__(self, *, total: int, page_size: int = 1000) -> None:
        super().__init__()
        self.total = total
        self.page_size = page_size
        self.offsets: list[int] = []
        self.limits: list[int] = []

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        del entity_path
        self.filter_exprs.append(filter_expr)
        self.offsets.append(offset)
        self.limits.append(limit)
        end = min(offset + limit, self.total)
        rows: list[Mapping[str, Any]] = []
        for index in range(offset, end):
            rows.append(
                {
                    "id": f"{index:08x}-1111-1111-1111-111111111111",
                    "code": f"SKU{index}",
                }
            )
        return rows


def test_load_product_id_to_code_paginates_beyond_first_page() -> None:
    client = _PaginatedProductClient(total=1005)
    result = asyncio.run(
        load_product_id_to_code(
            client,
            products_path="Основной склад/СНЕК",
            recursive=True,
        )
    )
    assert client.offsets == [0, 1000]
    assert client.limits == [1000, 1000]
    assert len(result) == 1005
    assert result[UUID("000003e8-1111-1111-1111-111111111111")] == "SKU1000"
