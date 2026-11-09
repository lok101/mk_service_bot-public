from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from src.infrastructure.integrations.moysklad.assortments import AssortmentRef


@runtime_checkable
class MoySkladClientPort(Protocol):
    async def get_entity_list(
        self,
        *,
        entity_path: str,
        filter_expr: str,
        limit: int,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]: ...

    async def post_entity(
        self,
        *,
        entity_path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    async def delete_entity(
        self,
        *,
        entity_path: str,
        entity_id: str,
    ) -> None: ...

    async def get_store_id_by_code(self, code: str) -> UUID: ...

    async def resolve_assortments_by_codes(self, codes: list[str]) -> dict[str, AssortmentRef]: ...

    async def get_stock_report_bystore(
        self,
        *,
        store_id: UUID,
    ) -> list[Mapping[str, Any]]: ...

    async def get_inventory_list(
        self,
        *,
        store_id: UUID,
        moment_from: datetime | None,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]: ...

    async def get_inventory_positions(
        self,
        *,
        inventory_id: str,
    ) -> list[Mapping[str, Any]]: ...

    async def get_move_list(
        self,
        *,
        moment_from: datetime,
        moment_to: datetime,
    ) -> list[Mapping[str, Any]]:
        """List moves; for store codes prefer ``expand`` (see moysklad.expand)."""
        ...

    async def get_move_positions(
        self,
        *,
        move_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Mapping[str, Any]]: ...

    async def get_moves_by_ids(
        self,
        *,
        move_ids: tuple[str, ...],
    ) -> list[Mapping[str, Any]]:
        """Batch fetch moves by id with positions expand (see moysklad.expand)."""
        ...

    async def get_store_code_by_id(self, store_id: UUID) -> str:
        """Single-store code lookup; avoid N+1 — prefer list ``expand``."""
        ...

    async def aclose(self) -> None: ...
