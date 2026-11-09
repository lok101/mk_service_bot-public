from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from beartype import beartype

from src.application.micromarket_loading.ports import SupplyOrderCategoryFactsSnapshotPort
from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    SupplyOrderCategoryProductFacts,
)


@beartype
def _as_utc(value: datetime) -> datetime:
    """Normalize naive (Mongo/BSON) or aware datetimes to UTC for age math."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCategoryFactsFromSnapshot:
    """Read-path adapter: snapshot → SupplyOrderCategoryFactsPort contract."""

    store: SupplyOrderCategoryFactsSnapshotPort
    now: Callable[[], datetime]
    staleness_seconds: int

    @beartype
    def fetch_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Sequence[SupplyOrderCategoryProductFacts] | SupplyOrderCategoryFactsFetchFailed:
        unique = tuple(dict.fromkeys(code.strip() for code in catalog_codes if code.strip()))
        if not unique:
            return ()
        snapshot = self.store.get()
        if snapshot is None:
            return SupplyOrderCategoryFactsFetchFailed()
        age = _as_utc(self.now()) - _as_utc(snapshot.refreshed_at)
        if age > timedelta(seconds=self.staleness_seconds):
            return SupplyOrderCategoryFactsFetchFailed()
        facts: list[SupplyOrderCategoryProductFacts] = []
        for code in unique:
            row = snapshot.facts_by_catalog_code.get(code)
            if row is None:
                return SupplyOrderCategoryFactsFetchFailed()
            facts.append(
                SupplyOrderCategoryProductFacts(
                    catalog_code=code,
                    folder_ancestor_ids=row.folder_ancestor_ids,
                    shelf_life_days=row.shelf_life_days,
                ),
            )
        return tuple(facts)
