from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from beartype import beartype

from src.application.micromarket_loading.move_gateway import MoveAlreadyGone, MoveDeleteFailed
from src.application.shared.async_bridge import run_coroutine_sync
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.integrations.moysklad.document_payload import (
    assortment_position_rows,
    organization_meta,
    project_meta,
    store_meta,
)
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladAPIError,
    MoySkladConnectionError,
    MoySkladRequestError,
)
from src.infrastructure.integrations.moysklad.quantities import MoySkladLinePosition
from src.infrastructure.integrations.moysklad.timezone import format_moment, parse_moment
from src.infrastructure.snack_loading.ms_loading import (
    available_from_stock_bystore_rows,
    pick_store_id_in_warehouses_path,
)

_EXTERNAL_CODE_PREFIX = "micromarket-loading:"
_LAUNCH_IDEMPOTENCY_WINDOW = timedelta(hours=2)


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladMicromarketMoveClient:
    client: MoySkladClientPort
    main_warehouse_id: UUID
    organization_id: UUID
    project_id: UUID
    warehouses_path: str
    warehouses_recursive: bool = False
    _stock_report_rows: list[list[Mapping[str, Any]] | None] = field(
        default_factory=lambda: [None],
        compare=False,
        hash=False,
    )
    _product_id_by_code: dict[str, UUID] = field(
        default_factory=dict,
        compare=False,
        hash=False,
    )

    @beartype
    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        return run_coroutine_sync(
            self._create(
                order_id=order_id,
                machine_code=machine_code,
                positions=positions,
            ),
        )

    @beartype
    def delete_move(self, *, move_id: str) -> None:
        run_coroutine_sync(self._delete(move_id=move_id))

    @beartype
    def move_moment(self, *, move_id: str) -> datetime | None:
        return run_coroutine_sync(self._move_moment(move_id=move_id))

    @beartype
    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        return run_coroutine_sync(
            self._existing_move_for_order_is_stale(order_id=order_id, now=now),
        )

    @beartype
    def warehouse_qty(self, product_code: str) -> Decimal:
        return self.warehouse_qty_by_codes([product_code]).get(product_code, Decimal("0"))

    @beartype
    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        return run_coroutine_sync(self._warehouse_qty_by_codes(product_codes=product_codes))

    @beartype
    async def _create(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        external_code = f"{_EXTERNAL_CODE_PREFIX}{order_id}"
        existing_id = await self._existing_move_id(external_code=external_code)
        if existing_id is not None:
            return existing_id

        trashed_id = await self._trashed_move_id(external_code=external_code)
        if trashed_id is not None:
            msg = (
                f"MoySklad move externalCode={external_code!r} is in trash "
                f"(id={trashed_id}); empty trash or restore+delete permanently, "
                "then retry create"
            )
            raise RuntimeError(msg)

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
            "description": order_id,
            "externalCode": external_code,
            "applicable": True,
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

        # Concurrent launch can POST twice with the same externalCode. Keep one
        # document and drop our duplicate so rollback targets a single move.
        winner_id = await self._existing_move_id(external_code=external_code)
        if winner_id is not None and winner_id != move_id:
            with contextlib.suppress(MoveAlreadyGone, MoveDeleteFailed):
                await self._delete(move_id=move_id)
            return winner_id
        return move_id

    @beartype
    async def _existing_move_row(self, *, external_code: str) -> Mapping[str, Any] | None:
        # Exclude trash: deleted moves still match bare externalCode and would be
        # "reused" while remaining invisible in the normal MoySklad UI.
        existing = await self.client.get_entity_list(
            entity_path="move",
            filter_expr=f"externalCode={external_code};isDeleted=false",
            limit=100,
        )
        ids = [
            row.get("id")
            for row in existing
            if isinstance(row, Mapping) and isinstance(row.get("id"), str) and row.get("id")
        ]
        if not ids:
            return None
        winner_id = min(str(value) for value in ids)
        for row in existing:
            if isinstance(row, Mapping) and row.get("id") == winner_id:
                return row
        return None

    @beartype
    async def _existing_move_id(self, *, external_code: str) -> str | None:
        row = await self._existing_move_row(external_code=external_code)
        if row is None:
            return None
        move_id = row.get("id")
        return move_id if isinstance(move_id, str) and move_id else None

    @beartype
    async def _existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        external_code = f"{_EXTERNAL_CODE_PREFIX}{order_id}"
        row = await self._existing_move_row(external_code=external_code)
        if row is None:
            return False
        moment_value = row.get("moment")
        if moment_value is None:
            return False
        move_moment = parse_moment(moment_value)
        return now - move_moment > _LAUNCH_IDEMPOTENCY_WINDOW

    @beartype
    async def _move_moment(self, *, move_id: str) -> datetime | None:
        rows = await self.client.get_moves_by_ids(move_ids=(move_id,))
        if not rows:
            return None
        row = rows[0]
        moment_value = row.get("moment") if isinstance(row, Mapping) else None
        if moment_value is None:
            return None
        return parse_moment(moment_value)

    @beartype
    async def _trashed_move_id(self, *, external_code: str) -> str | None:
        trashed = await self.client.get_entity_list(
            entity_path="move",
            filter_expr=f"externalCode={external_code};isDeleted=true",
            limit=1,
        )
        if not trashed:
            return None
        move_id = trashed[0].get("id")
        return move_id if isinstance(move_id, str) and move_id else None

    @beartype
    async def _delete(self, *, move_id: str) -> None:
        try:
            await self.client.delete_entity(entity_path="move", entity_id=move_id)
        except MoySkladRequestError as error:
            if error.status == 404:
                raise MoveAlreadyGone from error
            raise MoveDeleteFailed(str(error)) from error
        except MoySkladAPIError as error:
            if "HTTP 404" in str(error):
                raise MoveAlreadyGone from error
            raise MoveDeleteFailed(str(error)) from error
        except MoySkladConnectionError as error:
            raise MoveDeleteFailed(str(error)) from error

    @beartype
    async def _stock_rows_cached(self) -> list[Mapping[str, Any]]:
        cached = self._stock_report_rows[0]
        if cached is not None:
            return cached
        rows = await self.client.get_stock_report_bystore(store_id=self.main_warehouse_id)
        self._stock_report_rows[0] = rows
        return rows

    @beartype
    async def _warehouse_qty_by_codes(
        self,
        *,
        product_codes: Sequence[str],
    ) -> dict[str, Decimal]:
        unique = list(dict.fromkeys(code for code in product_codes if code))
        result: dict[str, Decimal] = {code: Decimal("0") for code in unique}
        if not unique:
            return result
        rows = await self._stock_rows_cached()
        catalog = frozenset(unique)
        available = available_from_stock_bystore_rows(
            rows,
            store_id=self.main_warehouse_id,
            product_id_to_code={},
            catalog_codes=catalog,
        )
        missing = [code for code in unique if code not in available]
        if missing:
            assortments = await self.client.resolve_assortments_by_codes(missing)
            product_id_to_code: dict[UUID, str] = {
                ref.id: code for code, ref in assortments.items()
            }
            for code, ref in assortments.items():
                self._product_id_by_code[code] = ref.id
            resolved = available_from_stock_bystore_rows(
                rows,
                store_id=self.main_warehouse_id,
                product_id_to_code=product_id_to_code,
                catalog_codes=frozenset(missing),
            )
            available = {**available, **resolved}
        for code in unique:
            result[code] = available.get(code, Decimal("0"))
        return result
