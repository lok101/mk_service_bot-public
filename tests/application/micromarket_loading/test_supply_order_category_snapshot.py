from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    SupplyOrderCategoryProductFacts,
)
from src.application.micromarket_loading.supply_order_category_facts_from_snapshot import (
    SupplyOrderCategoryFactsFromSnapshot,
)
from src.application.micromarket_loading.supply_order_category_snapshot import (
    SupplyOrderCategoryFactRow,
    SupplyOrderCategoryFactsSnapshot,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemorySupplyOrderCategoryFactsSnapshotStore,
)

_NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
_CODE = "ms-2311"


def _row() -> SupplyOrderCategoryFactRow:
    return SupplyOrderCategoryFactRow(
        folder_ancestor_ids=("child", "ready"),
        shelf_life_days=5,
    )


def test_replace_then_get_returns_snapshot() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    snapshot = SupplyOrderCategoryFactsSnapshot(
        refreshed_at=_NOW,
        facts_by_catalog_code={_CODE: _row()},
    )
    store.replace(snapshot)
    got = store.get()
    assert got is not None
    assert got.refreshed_at == _NOW
    assert got.facts_by_catalog_code[_CODE].shelf_life_days == 5


def test_adapter_happy_returns_facts() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    store.replace(
        SupplyOrderCategoryFactsSnapshot(
            refreshed_at=_NOW,
            facts_by_catalog_code={_CODE: _row()},
        ),
    )
    port = SupplyOrderCategoryFactsFromSnapshot(
        store=store,
        now=lambda: _NOW,
        staleness_seconds=600,
    )
    result = port.fetch_by_catalog_codes((_CODE,))
    assert not isinstance(result, SupplyOrderCategoryFactsFetchFailed)
    assert result == (
        SupplyOrderCategoryProductFacts(
            catalog_code=_CODE,
            folder_ancestor_ids=("child", "ready"),
            shelf_life_days=5,
        ),
    )


def test_adapter_stale_returns_fetch_failed() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    store.replace(
        SupplyOrderCategoryFactsSnapshot(
            refreshed_at=_NOW - timedelta(seconds=601),
            facts_by_catalog_code={_CODE: _row()},
        ),
    )
    port = SupplyOrderCategoryFactsFromSnapshot(
        store=store,
        now=lambda: _NOW,
        staleness_seconds=600,
    )
    assert isinstance(
        port.fetch_by_catalog_codes((_CODE,)),
        SupplyOrderCategoryFactsFetchFailed,
    )


def test_adapter_missing_code_returns_fetch_failed() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    store.replace(
        SupplyOrderCategoryFactsSnapshot(
            refreshed_at=_NOW,
            facts_by_catalog_code={_CODE: _row()},
        ),
    )
    port = SupplyOrderCategoryFactsFromSnapshot(
        store=store,
        now=lambda: _NOW,
        staleness_seconds=600,
    )
    assert isinstance(
        port.fetch_by_catalog_codes((_CODE, "missing")),
        SupplyOrderCategoryFactsFetchFailed,
    )


def test_adapter_empty_snapshot_returns_fetch_failed() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    port = SupplyOrderCategoryFactsFromSnapshot(
        store=store,
        now=lambda: _NOW,
        staleness_seconds=600,
    )
    assert isinstance(
        port.fetch_by_catalog_codes((_CODE,)),
        SupplyOrderCategoryFactsFetchFailed,
    )


def test_adapter_naive_refreshed_at_vs_aware_now_does_not_raise() -> None:
    """Mongo/pymongo may strip tzinfo; Create must fail-closed, not TypeError."""
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    store.replace(
        SupplyOrderCategoryFactsSnapshot(
            refreshed_at=datetime(2026, 10, 30, 12, 0),  # naive
            facts_by_catalog_code={_CODE: _row()},
        ),
    )
    port = SupplyOrderCategoryFactsFromSnapshot(
        store=store,
        now=lambda: _NOW,
        staleness_seconds=600,
    )
    result = port.fetch_by_catalog_codes((_CODE,))
    assert not isinstance(result, SupplyOrderCategoryFactsFetchFailed)
    assert result[0].catalog_code == _CODE


def test_adapter_naive_stale_refreshed_at_returns_fetch_failed() -> None:
    store = InMemorySupplyOrderCategoryFactsSnapshotStore()
    store.replace(
        SupplyOrderCategoryFactsSnapshot(
            refreshed_at=datetime(2026, 10, 30, 11, 0),  # naive, >600s before _NOW
            facts_by_catalog_code={_CODE: _row()},
        ),
    )
    port = SupplyOrderCategoryFactsFromSnapshot(
        store=store,
        now=lambda: _NOW,
        staleness_seconds=600,
    )
    assert isinstance(
        port.fetch_by_catalog_codes((_CODE,)),
        SupplyOrderCategoryFactsFetchFailed,
    )
