from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCategoryFactRow:
    folder_ancestor_ids: tuple[str, ...]
    shelf_life_days: int | None


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCategoryFactsSnapshot:
    refreshed_at: datetime
    facts_by_catalog_code: Mapping[str, SupplyOrderCategoryFactRow]
