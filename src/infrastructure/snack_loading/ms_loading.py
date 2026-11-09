from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from beartype import beartype

from src.application.snack_loading.ports import SnackStoreResolveError
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.constants import CREATED_AUTOMATICALLY
from src.infrastructure.integrations.moysklad.document_payload import (
    assortment_position_rows,
    organization_meta,
    project_meta,
    store_meta,
)
from src.infrastructure.integrations.moysklad.quantities import MoySkladLinePosition
from src.infrastructure.integrations.moysklad.timezone import format_moment
from src.infrastructure.snack_loading.food_product_codes import path_name_in_scope

_UUID_IN_HREF = re.compile(
    r"/entity/(?:product|variant|bundle|service)/"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


@beartype
def product_id_from_stock_row_meta(row: Mapping[str, Any]) -> UUID | None:
    meta = row.get("meta")
    if not isinstance(meta, dict):
        return None
    href = meta.get("href")
    if not isinstance(href, str):
        return None
    match = _UUID_IN_HREF.search(href)
    if match is None:
        return None
    return UUID(match.group(1))


@beartype
def stock_qty_for_store(row: Mapping[str, Any], *, store_id: UUID) -> Decimal | None:
    """Return qty from ``stockByStore`` for ``store_id``; ignore top-level ``stock``."""
    by_store = row.get("stockByStore")
    if not isinstance(by_store, list):
        return None
    target = str(store_id)
    for entry in by_store:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("meta")
        href = meta.get("href") if isinstance(meta, dict) else None
        if not isinstance(href, str) or target not in href:
            continue
        raw = entry.get("stock")
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            return Decimal(str(raw))
        if isinstance(raw, str):
            return Decimal(raw)
    return None


@beartype
def available_from_stock_bystore_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    store_id: UUID,
    product_id_to_code: Mapping[UUID, str],
    catalog_codes: Set[str] | None = None,
) -> dict[str, Decimal]:
    available: dict[str, Decimal] = {}
    for row in rows:
        product_id = product_id_from_stock_row_meta(row)
        code: str | None = None
        if product_id is not None:
            code = product_id_to_code.get(product_id)
        if code is None and catalog_codes is not None:
            row_code = row.get("code")
            if isinstance(row_code, str):
                stripped = row_code.strip()
                if stripped in catalog_codes:
                    code = stripped
        if code is None:
            continue
        qty = stock_qty_for_store(row, store_id=store_id)
        if qty is None:
            continue
        available[code] = available.get(code, Decimal("0")) + qty
    return available


@beartype
def pick_store_id_in_warehouses_path(
    rows: Sequence[Mapping[str, Any]],
    *,
    machine_code: str,
    warehouses_path: str,
    recursive: bool,
) -> UUID:
    matches: list[UUID] = []
    for row in rows:
        code = row.get("code")
        if not isinstance(code, str) or code.strip() != machine_code:
            continue
        path_name = row.get("pathName")
        if not isinstance(path_name, str):
            continue
        if not path_name_in_scope(
            path_name,
            path_prefix=warehouses_path,
            recursive=recursive,
        ):
            continue
        raw_id = row.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            continue
        matches.append(UUID(raw_id))
    if not matches:
        msg = (
            f"Store code {machine_code!r} not found under SNACK_LOADING_WAREHOUSES_PATH "
            f"{warehouses_path!r}"
        )
        raise SnackStoreResolveError(msg)
    if len(matches) > 1:
        msg = f"Multiple stores with code {machine_code!r} under warehouses path"
        raise SnackStoreResolveError(msg)
    return matches[0]


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladSnackMainStockReader:
    client: MoySkladClientPort
    main_warehouse_id: UUID
    product_id_to_code: Mapping[UUID, str]

    @beartype
    def available_by_product(self) -> dict[str, Decimal]:
        return asyncio.run(self._fetch())

    @beartype
    async def _fetch(self) -> dict[str, Decimal]:
        rows = await self.client.get_stock_report_bystore(store_id=self.main_warehouse_id)
        return available_from_stock_bystore_rows(
            rows,
            store_id=self.main_warehouse_id,
            product_id_to_code=self.product_id_to_code,
        )


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladSnackMoveClient:
    client: MoySkladClientPort
    main_warehouse_id: UUID
    organization_id: UUID
    project_id: UUID
    warehouses_path: str
    warehouses_recursive: bool = False

    @beartype
    def create_move(
        self,
        *,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        return asyncio.run(self._create(machine_code=machine_code, positions=positions))

    @beartype
    async def _create(
        self,
        *,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        store_rows = await self.client.get_entity_list(
            entity_path="store",
            filter_expr=f"code={machine_code}",
            limit=100,
        )
        target_store_id = pick_store_id_in_warehouses_path(
            store_rows,
            machine_code=machine_code,
            warehouses_path=self.warehouses_path,
            recursive=self.warehouses_recursive,
        )
        ms_positions = [
            MoySkladLinePosition(product_code=code, quantity=float(qty)) for code, qty in positions
        ]
        position_rows = await assortment_position_rows(self.client, ms_positions)
        body: dict[str, object] = {
            "moment": format_moment(datetime.now(tz=UTC)),
            "description": CREATED_AUTOMATICALLY,
            "organization": organization_meta(self.organization_id),
            "project": project_meta(self.project_id),
            "sourceStore": store_meta(self.main_warehouse_id),
            "targetStore": store_meta(target_store_id),
            "positions": position_rows,
        }
        created = await self.client.post_entity(entity_path="move", body=body)
        move_id = created.get("id")
        if not isinstance(move_id, str) or not move_id:
            msg = "MoySklad move response missing id"
            raise RuntimeError(msg)
        return move_id


@beartype
async def load_product_id_to_code(
    client: MoySkladClientPort,
    *,
    products_path: str,
    recursive: bool,
) -> dict[UUID, str]:
    """Build product id → code from MoySklad products under ``pathName``."""
    if not products_path:
        filter_expr = ""
    elif recursive:
        filter_expr = f"pathName~={products_path}"
    else:
        filter_expr = f"pathName={products_path}"
    # Paginate: a single limit=1000 page silently truncates large catalogs
    # (same pattern as get_stock_report_bystore / get_move_list).
    limit = 1000
    offset = 0
    result: dict[UUID, str] = {}
    while True:
        rows = await client.get_entity_list(
            entity_path="product",
            filter_expr=filter_expr,
            limit=limit,
            offset=offset,
        )
        for row in rows:
            raw_id = row.get("id")
            code = row.get("code")
            if not isinstance(raw_id, str) or not isinstance(code, str) or not code.strip():
                continue
            result[UUID(raw_id)] = code.strip()
        if len(rows) < limit:
            break
        offset += limit
    return result


@beartype
async def load_food_product_codes(
    client: MoySkladClientPort,
    *,
    food_products_path: str,
    recursive: bool,
) -> frozenset[str]:
    mapping = await load_product_id_to_code(
        client,
        products_path=food_products_path,
        recursive=recursive,
    )
    return frozenset(mapping.values())
