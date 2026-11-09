from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from beartype import beartype

from src.application.micromarket_loading.ms_catalog_code import (
    resolve_planogram_line_ms_catalog_code,
)
from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    MicromarketWarehouseStockSnapshotPort,
)
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.application.product_identity.ports import DomainProductStore

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class WarehouseStockQtyFetcher(Protocol):
    def fetch_qty_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Mapping[str, Decimal]: ...


@beartype
def collect_planogram_catalog_codes(
    *,
    planograms: MicromarketPlanogramStore,
    products: DomainProductStore | None,
) -> tuple[str, ...]:
    codes: list[str] = []
    seen: set[str] = set()
    for planogram in planograms.list_all():
        for line in planogram.lines:
            catalog_code = resolve_planogram_line_ms_catalog_code(
                products,
                product_code=line.product_code,
                domain_product_id=line.domain_product_id,
            )
            if catalog_code is None or not catalog_code.strip():
                continue
            if catalog_code in seen:
                continue
            seen.add(catalog_code)
            codes.append(catalog_code)
    return tuple(codes)


@beartype
@dataclass(frozen=True, slots=True)
class SyncMicromarketWarehouseStock:
    snapshot_store: MicromarketWarehouseStockSnapshotPort
    planograms: MicromarketPlanogramStore
    products: DomainProductStore | None
    warehouse_id: UUID
    fetcher: WarehouseStockQtyFetcher

    @beartype
    def sync_once(self, *, now: datetime | None = None) -> MainWarehouseStockSnapshot:
        started = time.perf_counter()
        refreshed_at = now if now is not None else datetime.now(tz=UTC)
        codes = collect_planogram_catalog_codes(
            planograms=self.planograms,
            products=self.products,
        )
        if not codes:
            snapshot = MainWarehouseStockSnapshot(
                warehouse_id=self.warehouse_id,
                refreshed_at=refreshed_at,
                qty_by_catalog_code={},
            )
            self.snapshot_store.replace(snapshot)
            _LOGGER.info(
                "micromarket_warehouse_stock_sync_empty_union",
                extra={
                    "warehouse_id": str(self.warehouse_id),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return snapshot
        fetched = self.fetcher.fetch_qty_by_catalog_codes(codes)
        qty_by_code: dict[str, Decimal] = {code: fetched.get(code, Decimal("0")) for code in codes}
        snapshot = MainWarehouseStockSnapshot(
            warehouse_id=self.warehouse_id,
            refreshed_at=refreshed_at,
            qty_by_catalog_code=qty_by_code,
        )
        self.snapshot_store.replace(snapshot)
        _LOGGER.info(
            "micromarket_warehouse_stock_sync_ok",
            extra={
                "warehouse_id": str(self.warehouse_id),
                "codes": len(codes),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return snapshot
