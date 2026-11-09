from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from src.infrastructure.integrations.moysklad.assortments import AssortmentRef

_DEFAULT_WAREHOUSE_ID = UUID("00000000-0000-0000-0000-000000000003")
_DEFAULT_PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000004")


class FakeMoySkladClient:
    def __init__(
        self,
        *,
        warehouse_id: UUID = _DEFAULT_WAREHOUSE_ID,
        product_id: UUID = _DEFAULT_PRODUCT_ID,
        move_rows: list[Mapping[str, Any]] | None = None,
        store_codes_by_id: dict[UUID, str] | None = None,
        store_code_errors_by_id: dict[UUID, Exception] | None = None,
        store_ids_by_code: dict[str, UUID] | None = None,
        store_id_by_code_errors: dict[str, Exception] | None = None,
        move_list_error: Exception | None = None,
        get_entity_list_error: Exception | None = None,
    ) -> None:
        self.posted_payloads: list[dict[str, object]] = []
        self.posted_entity_paths: list[str] = []
        self.stock_report_rows: list[Mapping[str, Any]] = []
        self.inventory_rows: list[Mapping[str, Any]] = []
        self.inventory_positions: dict[str, list[Mapping[str, Any]]] = {}
        self.move_rows: list[Mapping[str, Any]] = list(move_rows or [])
        self.move_positions: dict[str, list[Mapping[str, Any]]] = {}
        self.move_list_calls: list[tuple[datetime, datetime]] = []
        self.get_moves_by_ids_calls: list[tuple[str, ...]] = []
        self.get_move_positions_calls: list[str] = []
        self.get_moves_by_ids_error: Exception | None = None
        self.move_list_error = move_list_error
        self.get_entity_list_error = get_entity_list_error
        self.store_codes_by_id: dict[UUID, str] = dict(store_codes_by_id or {})
        self.store_code_errors_by_id: dict[UUID, Exception] = dict(
            store_code_errors_by_id or {},
        )
        self.store_ids_by_code: dict[str, UUID] = dict(store_ids_by_code or {})
        self.store_id_by_code_errors: dict[str, Exception] = dict(
            store_id_by_code_errors or {},
        )
        self.get_store_id_by_code_calls: list[str] = []
        self.get_store_code_by_id_calls: list[UUID] = []
        self.next_post_error: Exception | None = None
        self.raise_after_post: Exception | None = None
        self._warehouse_id = warehouse_id
        self._product_id = product_id

    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        _ = entity_path
        if self.get_entity_list_error is not None:
            raise self.get_entity_list_error
        if not filter_expr.startswith("externalCode="):
            return []
        external_code = filter_expr[len("externalCode=") :]
        rows = [
            payload
            for payload in self.posted_payloads
            if str(payload.get("externalCode")) == external_code
        ]
        return rows[offset : offset + limit]

    async def post_entity(
        self,
        *,
        entity_path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self.next_post_error is not None:
            error = self.next_post_error
            self.next_post_error = None
            raise error
        self.posted_entity_paths.append(entity_path)
        payload = dict(body)
        self.posted_payloads.append(payload)
        if self.raise_after_post is not None:
            error = self.raise_after_post
            self.raise_after_post = None
            raise error
        return payload

    async def delete_entity(self, *, entity_path: str, entity_id: str) -> None:
        raise NotImplementedError(
            f"FakeMoySkladClient.delete_entity({entity_path!r}, {entity_id!r})",
        )

    async def get_store_id_by_code(self, code: str) -> UUID:
        self.get_store_id_by_code_calls.append(code)
        if code in self.store_id_by_code_errors:
            raise self.store_id_by_code_errors[code]
        if code in self.store_ids_by_code:
            return self.store_ids_by_code[code]
        return self._warehouse_id

    async def resolve_assortments_by_codes(self, codes: list[str]) -> dict[str, AssortmentRef]:
        return {code: AssortmentRef(id=self._product_id, entity_type="product") for code in codes}

    async def get_stock_report_bystore(
        self,
        *,
        store_id: UUID,
    ) -> list[Mapping[str, Any]]:
        _ = store_id
        return list(self.stock_report_rows)

    async def get_inventory_list(
        self,
        *,
        store_id: UUID,
        moment_from: datetime | None,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        _ = store_id, moment_from, moment_to
        return list(self.inventory_rows)

    async def get_inventory_positions(
        self,
        *,
        inventory_id: str,
    ) -> list[Mapping[str, Any]]:
        return list(self.inventory_positions.get(inventory_id, []))

    async def get_move_list(
        self,
        *,
        moment_from: datetime,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        self.move_list_calls.append((moment_from, moment_to))
        if self.move_list_error is not None:
            raise self.move_list_error
        return list(self.move_rows)

    async def get_move_positions(
        self,
        *,
        move_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]:
        self.get_move_positions_calls.append(move_id)
        rows = list(self.move_positions.get(move_id, []))
        return rows[offset : offset + limit]

    async def get_moves_by_ids(
        self,
        *,
        move_ids: tuple[str, ...],
    ) -> list[Mapping[str, Any]]:
        self.get_moves_by_ids_calls.append(move_ids)
        if self.get_moves_by_ids_error is not None:
            raise self.get_moves_by_ids_error
        result: list[Mapping[str, Any]] = []
        for move_id in move_ids:
            row = next((item for item in self.move_rows if str(item.get("id")) == move_id), None)
            base = dict(row) if row is not None else {"id": move_id}
            positions = list(self.move_positions.get(move_id, []))
            # Simulate MS expand page cap: first 100 rows + meta.size when longer.
            page = positions[:100]
            meta: dict[str, object] = {"size": len(positions)}
            base["positions"] = {"meta": meta, "rows": page}
            result.append(base)
        return result

    async def get_store_code_by_id(self, store_id: UUID) -> str:
        self.get_store_code_by_id_calls.append(store_id)
        if store_id in self.store_code_errors_by_id:
            raise self.store_code_errors_by_id[store_id]
        if store_id in self.store_codes_by_id:
            return self.store_codes_by_id[store_id]
        return f"store-{store_id}"

    async def aclose(self) -> None:
        pass
