from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    SupplyOrderCategoryFactsPort,
    SupplyOrderCategoryFactsSnapshotPort,
)
from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
)
from src.application.micromarket_loading.supply_order_category_snapshot import (
    SupplyOrderCategoryFactRow,
    SupplyOrderCategoryFactsSnapshot,
)
from src.application.micromarket_loading.sync_warehouse_stock import (
    collect_planogram_catalog_codes,
)
from src.application.product_identity.ports import DomainProductStore

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class FolderParentIndexRefresh(Protocol):
    def refresh_folder_parent_index(self) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class SyncSupplyOrderCategoryFacts:
    snapshot_store: SupplyOrderCategoryFactsSnapshotPort
    planograms: MicromarketPlanogramStore
    products: DomainProductStore | None
    facts_fetcher: SupplyOrderCategoryFactsPort
    folder_index: FolderParentIndexRefresh | None = None

    @beartype
    def sync_once(self, *, now: datetime | None = None) -> SupplyOrderCategoryFactsSnapshot:
        started = time.perf_counter()
        refreshed_at = now if now is not None else datetime.now(tz=UTC)
        codes = collect_planogram_catalog_codes(
            planograms=self.planograms,
            products=self.products,
        )
        if not codes:
            snapshot = SupplyOrderCategoryFactsSnapshot(
                refreshed_at=refreshed_at,
                facts_by_catalog_code={},
            )
            self.snapshot_store.replace(snapshot)
            _LOGGER.info(
                "supply_order_category_facts_sync_empty_union",
                extra={"duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            return snapshot
        if self.folder_index is not None:
            self.folder_index.refresh_folder_parent_index()
        fetched = self.facts_fetcher.fetch_by_catalog_codes(codes)
        if isinstance(fetched, SupplyOrderCategoryFactsFetchFailed):
            raise RuntimeError("supply_order_category_facts_fetch_failed")
        facts_by_code = {
            row.catalog_code: SupplyOrderCategoryFactRow(
                folder_ancestor_ids=row.folder_ancestor_ids,
                shelf_life_days=row.shelf_life_days,
            )
            for row in fetched
        }
        missing = codes_missing_from_facts(
            requested=codes,
            present=tuple(facts_by_code),
        )
        if missing:
            raise RuntimeError(
                f"supply_order_category_facts_incomplete missing={len(missing)}",
            )
        snapshot = SupplyOrderCategoryFactsSnapshot(
            refreshed_at=refreshed_at,
            facts_by_catalog_code=facts_by_code,
        )
        self.snapshot_store.replace(snapshot)
        _LOGGER.info(
            "supply_order_category_facts_sync_ok",
            extra={
                "codes": len(codes),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return snapshot


@beartype
def codes_missing_from_facts(
    *,
    requested: Sequence[str],
    present: Sequence[str],
) -> tuple[str, ...]:
    have = set(present)
    return tuple(code for code in requested if code not in have)
