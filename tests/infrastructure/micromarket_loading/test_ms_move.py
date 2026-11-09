from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from src.application.micromarket_loading.move_gateway import MoveAlreadyGone, MoveDeleteFailed
from src.infrastructure.integrations.moysklad.assortments import AssortmentRef
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladAPIError,
    MoySkladConnectionError,
    MoySkladRequestError,
)
from src.infrastructure.micromarket_loading.ms_move import MoySkladMicromarketMoveClient

_WAREHOUSE = UUID("11111111-1111-1111-1111-111111111111")
_ORG = UUID("22222222-2222-2222-2222-222222222222")
_PROJECT = UUID("33333333-3333-3333-3333-333333333333")
_STORE = UUID("44444444-4444-4444-4444-444444444444")
_PRODUCT = UUID("55555555-5555-5555-5555-555555555555")
_VARIANT = UUID("66666666-6666-6666-6666-666666666666")
_WAREHOUSES_PATH = "Stores/Points"
_CATALOG_CODE = "2311"


def _store_href(store_id: UUID) -> str:
    return f"https://api.moysklad.ru/api/remap/1.2/entity/store/{store_id}"


def _variant_href(variant_id: UUID) -> str:
    return f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}"


class _FakeClient:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        *,
        stock_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.rows = rows or []
        self.stock_rows = stock_rows or []
        self.posts: list[dict[str, object]] = []
        self.delete_status: int | None = None
        self.delete_error: Exception | None = None
        self.stock_report_calls = 0
        self.resolve_calls: list[list[str]] = []

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        del limit, offset
        if "externalCode=" in filter_expr:
            code = ""
            for part in filter_expr.split(";"):
                if part.startswith("externalCode="):
                    code = part.split("=", 1)[1]
                    break
            want_deleted = "isDeleted=true" in filter_expr
            want_alive = "isDeleted=false" in filter_expr
            matched: list[dict[str, object]] = []
            for row in self.rows:
                if row.get("externalCode") != code:
                    continue
                is_deleted = bool(row.get("_deleted"))
                if want_deleted and not is_deleted:
                    continue
                if want_alive and is_deleted:
                    continue
                matched.append(row)
            return matched
        if filter_expr.startswith("code="):
            return [
                {"id": str(_STORE), "code": "701", "pathName": _WAREHOUSES_PATH},
            ]
        return []

    async def post_entity(
        self,
        *,
        entity_path: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        del entity_path
        self.posts.append(body)
        return {"id": "move-new"}

    async def delete_entity(self, *, entity_path: str, entity_id: str) -> None:
        del entity_path, entity_id
        if self.delete_error is not None:
            raise self.delete_error
        if self.delete_status is not None:
            raise MoySkladRequestError(self.delete_status, {"errors": [{"error": "fail"}]})

    async def get_stock_report_bystore(self, *, store_id: UUID) -> list[dict[str, object]]:
        del store_id
        self.stock_report_calls += 1
        return self.stock_rows

    async def resolve_assortments_by_codes(self, codes: list[str]) -> dict[str, AssortmentRef]:
        self.resolve_calls.append(list(codes))
        return {code: AssortmentRef(id=_PRODUCT, entity_type="product") for code in codes}

    async def get_store_id_by_code(self, code: str) -> UUID:
        del code
        return _STORE

    async def get_inventory_list(
        self,
        *,
        store_id: UUID,
        moment_from: datetime | None,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        del store_id, moment_from, moment_to
        return []

    async def get_inventory_positions(self, *, inventory_id: str) -> list[Mapping[str, Any]]:
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
        return "701"

    async def aclose(self) -> None:
        return None


def test_warehouse_qty_by_codes_uses_stock_row_code_without_variant_mapping() -> None:
    variant_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    stock_rows = [
        {
            "meta": {"href": _variant_href(variant_id), "type": "variant"},
            "code": _CATALOG_CODE,
            "stockByStore": [
                {
                    "meta": {"href": _store_href(_WAREHOUSE), "type": "store"},
                    "stock": 9.0,
                }
            ],
        }
    ]
    client = _FakeClient(stock_rows=stock_rows)
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    qty = gateway.warehouse_qty_by_codes([_CATALOG_CODE])
    assert qty[_CATALOG_CODE] == Decimal("9")
    assert client.resolve_calls == []


def test_warehouse_qty_by_codes_resolves_only_missing_codes() -> None:
    stock_rows = [
        {
            "meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/product/{_PRODUCT}"},
            "code": _CATALOG_CODE,
            "stockByStore": [
                {
                    "meta": {"href": _store_href(_WAREHOUSE), "type": "store"},
                    "stock": 4.0,
                }
            ],
        },
        {
            "meta": {"href": _variant_href(_VARIANT), "type": "variant"},
            "stockByStore": [
                {
                    "meta": {"href": _store_href(_WAREHOUSE), "type": "store"},
                    "stock": 11.0,
                }
            ],
        },
    ]
    client = _FakeClient(stock_rows=stock_rows)

    async def _resolve(codes: list[str]) -> dict[str, AssortmentRef]:
        client.resolve_calls.append(list(codes))
        return {code: AssortmentRef(id=_VARIANT, entity_type="variant") for code in codes}

    client.resolve_assortments_by_codes = _resolve  # type: ignore[method-assign]
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    qty = gateway.warehouse_qty_by_codes([_CATALOG_CODE, "MISSING"])
    assert qty[_CATALOG_CODE] == Decimal("4")
    assert qty["MISSING"] == Decimal("11")
    assert client.resolve_calls == [["MISSING"]]


def test_warehouse_qty_by_codes_treats_unmapped_variant_meta_as_zero() -> None:
    stock_rows = [
        {
            "meta": {"href": _variant_href(_VARIANT), "type": "variant"},
            "stockByStore": [
                {
                    "meta": {"href": _store_href(_WAREHOUSE), "type": "store"},
                    "stock": 7.0,
                }
            ],
        }
    ]
    client = _FakeClient(stock_rows=stock_rows)
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    qty = gateway.warehouse_qty_by_codes([_CATALOG_CODE])
    assert qty[_CATALOG_CODE] == Decimal("0")


def test_warehouse_qty_by_codes_reuses_single_stock_report() -> None:
    client = _FakeClient()
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    qty = gateway.warehouse_qty_by_codes(["2311", "2312"])
    assert qty["2311"] == Decimal("0")
    assert qty["2312"] == Decimal("0")
    assert client.stock_report_calls == 1


def test_create_move_body_is_conducted_and_named_by_order_id() -> None:
    client = _FakeClient()
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    move_id = gateway.create_move(
        order_id="order-1",
        machine_code="701",
        positions=(("2311", Decimal("2")),),
    )
    assert move_id == "move-new"
    body = client.posts[0]
    assert body["applicable"] is True
    assert body["externalCode"] == "micromarket-loading:order-1"
    assert "order-1" in str(body["description"])
    names = [
        name for name in dir(MoySkladMicromarketMoveClient) if "update" in name or "edit" in name
    ]
    assert names == []


def test_create_move_reuses_existing_external_code() -> None:
    client = _FakeClient(
        rows=[{"id": "move-old", "externalCode": "micromarket-loading:order-1"}],
    )
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    move_id = gateway.create_move(
        order_id="order-1",
        machine_code="701",
        positions=(("2311", Decimal("2")),),
    )
    assert move_id == "move-old"
    assert client.posts == []


def test_create_move_rejects_when_only_trashed_external_code_exists() -> None:
    client = _FakeClient(
        rows=[
            {
                "id": "move-trash",
                "externalCode": "micromarket-loading:order-1",
                "_deleted": True,
            },
        ],
    )
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    with pytest.raises(RuntimeError, match="trash"):
        gateway.create_move(
            order_id="order-1",
            machine_code="701",
            positions=(("2311", Decimal("2")),),
        )
    assert client.posts == []


def test_delete_move_missing_document_is_already_gone() -> None:
    client = _FakeClient()
    client.delete_status = 404
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    with pytest.raises(MoveAlreadyGone):
        gateway.delete_move(move_id="move-old")


def test_delete_move_other_error_is_not_already_gone() -> None:
    client = _FakeClient()
    client.delete_status = 500
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    with pytest.raises(MoveDeleteFailed):
        gateway.delete_move(move_id="move-old")


def test_delete_move_api_error_404_is_already_gone() -> None:
    client = _FakeClient()
    client.delete_error = MoySkladAPIError("MoySklad HTTP 404: {}")
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    with pytest.raises(MoveAlreadyGone):
        gateway.delete_move(move_id="move-old")


def test_delete_move_api_error_other_is_delete_failed() -> None:
    client = _FakeClient()
    client.delete_error = MoySkladAPIError("MoySklad HTTP 500: {}")
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    with pytest.raises(MoveDeleteFailed):
        gateway.delete_move(move_id="move-old")


def test_delete_move_connection_error_is_delete_failed() -> None:
    client = _FakeClient()
    client.delete_error = MoySkladConnectionError("reset")
    gateway = MoySkladMicromarketMoveClient(
        client=client,
        main_warehouse_id=_WAREHOUSE,
        organization_id=_ORG,
        project_id=_PROJECT,
        warehouses_path=_WAREHOUSES_PATH,
        warehouses_recursive=False,
    )
    with pytest.raises(MoveDeleteFailed):
        gateway.delete_move(move_id="move-old")
