from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    SupplyOrderCategoryProductFacts,
)
from src.application.micromarket_loading.supply_order_category_snapshot import (
    SupplyOrderCategoryFactRow,
    SupplyOrderCategoryFactsSnapshot,
)
from src.application.micromarket_loading.sync_supply_order_category_facts import (
    SyncSupplyOrderCategoryFacts,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketPlanogramStore,
    InMemorySupplyOrderCategoryFactsSnapshotStore,
)

_NOW = datetime(2026, 10, 30, tzinfo=UTC)


def _planogram() -> MicromarketPlanogram:
    return MicromarketPlanogram(
        machine_code="mm-1",
        updated_at=_NOW,
        lines=(
            MicromarketPlanogramLine(
                product_code="ms-1",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
            ),
        ),
    )


class _OkFetcher:
    def fetch_by_catalog_codes(self, catalog_codes):
        return tuple(
            SupplyOrderCategoryProductFacts(
                catalog_code=code,
                folder_ancestor_ids=("ready",),
                shelf_life_days=5,
            )
            for code in catalog_codes
        )


class _FailFetcher:
    def fetch_by_catalog_codes(self, catalog_codes):
        return SupplyOrderCategoryFactsFetchFailed()


class _IndexRefresh:
    def __init__(self) -> None:
        self.calls = 0

    def refresh_folder_parent_index(self) -> None:
        self.calls += 1


def test_sync_replaces_snapshot_on_success() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(_planogram())
    sync = SyncSupplyOrderCategoryFacts(
        snapshot_store=store,
        planograms=planograms,
        products=None,
        facts_fetcher=_OkFetcher(),
    )
    snapshot = sync.sync_once(now=_NOW)
    assert store.get() is not None
    assert "ms-1" in snapshot.facts_by_catalog_code


def test_sync_failed_fetch_does_not_wipe() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    prior = SupplyOrderCategoryFactsSnapshot(
        refreshed_at=datetime(2026, 10, 29, tzinfo=UTC),
        facts_by_catalog_code={
            "ms-1": SupplyOrderCategoryFactRow(folder_ancestor_ids=("a",), shelf_life_days=1),
        },
    )
    store.replace(prior)
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(_planogram())
    sync = SyncSupplyOrderCategoryFacts(
        snapshot_store=store,
        planograms=planograms,
        products=None,
        facts_fetcher=_FailFetcher(),
    )
    try:
        sync.sync_once(now=_NOW)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
    kept = store.get()
    assert kept is not None
    assert kept.facts_by_catalog_code["ms-1"].shelf_life_days == 1


def test_sync_refreshes_folder_parent_index_before_fetch() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(_planogram())
    index = _IndexRefresh()
    sync = SyncSupplyOrderCategoryFacts(
        snapshot_store=store,
        planograms=planograms,
        products=None,
        facts_fetcher=_OkFetcher(),
        folder_index=index,
    )
    sync.sync_once(now=_NOW)
    assert index.calls == 1
