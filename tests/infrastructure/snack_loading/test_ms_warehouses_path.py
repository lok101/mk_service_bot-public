from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from src.application.snack_loading.ports import SnackStoreResolveError
from src.infrastructure.integrations.moysklad.assortments import AssortmentRef
from src.infrastructure.snack_loading.ms_loading import (
    MoySkladSnackMoveClient,
    pick_store_id_in_warehouses_path,
)

_WAREHOUSES = "Торговые автоматы CL/СНЕК, Екатеринбург"
_STORE = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_MAIN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_ORG = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_PROJECT = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


class _StoreListFakeClient:
    def __init__(self, store_rows: list[Mapping[str, Any]]) -> None:
        self.store_rows = store_rows
        self.posted_entity_paths: list[str] = []

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        del filter_expr, limit, offset
        if entity_path == "store":
            return list(self.store_rows)
        return []

    async def post_entity(
        self,
        *,
        entity_path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.posted_entity_paths.append(entity_path)
        del body
        return {"id": "should-not-post"}

    async def delete_entity(self, *, entity_path: str, entity_id: str) -> None:
        del entity_path, entity_id

    async def resolve_assortments_by_codes(self, codes: list[str]) -> dict[str, AssortmentRef]:
        del codes
        return {}

    async def get_store_id_by_code(self, code: str) -> UUID:
        del code
        return _STORE

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


def test_create_move_rejects_store_outside_warehouses_path() -> None:
    rows = [
        {
            "id": str(_STORE),
            "code": "501",
            "pathName": "Другой путь/Склад",
        }
    ]

    with pytest.raises(SnackStoreResolveError, match="WAREHOUSES_PATH"):
        pick_store_id_in_warehouses_path(
            rows,
            machine_code="501",
            warehouses_path=_WAREHOUSES,
            recursive=False,
        )


def test_create_move_raises_when_store_outside_warehouses_path() -> None:
    client = _StoreListFakeClient(
        store_rows=[
            {
                "id": str(_STORE),
                "code": "501",
                "pathName": "Другой путь/Склад",
            }
        ]
    )
    move_client = MoySkladSnackMoveClient(
        client=client,
        main_warehouse_id=_MAIN,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES,
        warehouses_recursive=False,
    )

    with pytest.raises(SnackStoreResolveError, match="WAREHOUSES_PATH"):
        move_client.create_move(
            machine_code="501",
            positions=(("SKU1", Decimal("1")),),
        )

    assert client.posted_entity_paths == []
