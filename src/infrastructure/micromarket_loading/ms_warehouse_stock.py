from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from beartype import beartype

from src.application.micromarket_loading.sync_warehouse_stock import WarehouseStockQtyFetcher
from src.application.shared.async_bridge import run_coroutine_sync
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.snack_loading.ms_loading import available_from_stock_bystore_rows


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladWarehouseStockFetcher(WarehouseStockQtyFetcher):
    client: MoySkladClientPort
    main_warehouse_id: UUID
    _product_id_by_code: dict[str, UUID] = field(
        default_factory=dict,
        compare=False,
        hash=False,
    )

    @beartype
    def fetch_qty_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Mapping[str, Decimal]:
        return run_coroutine_sync(self._fetch(product_codes=catalog_codes))

    @beartype
    async def _fetch(
        self,
        *,
        product_codes: Sequence[str],
    ) -> dict[str, Decimal]:
        unique = list(dict.fromkeys(code for code in product_codes if code))
        result: dict[str, Decimal] = {code: Decimal("0") for code in unique}
        if not unique:
            return result
        rows: list[Mapping[str, Any]] = await self.client.get_stock_report_bystore(
            store_id=self.main_warehouse_id,
        )
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
