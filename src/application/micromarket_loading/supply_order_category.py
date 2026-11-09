from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from beartype import beartype

from src.domain.micromarket_loading.supply_order import SupplyOrderLineCategory

SupplyOrderCategoryKind = Literal["snack", "ready_2", "ready_3", "ignore", "missing_days"]


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCategoryProductFacts:
    catalog_code: str
    folder_ancestor_ids: tuple[str, ...]
    shelf_life_days: int | None


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCategoryFactsFetchFailed:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCategoryClassifyResult:
    kind: SupplyOrderCategoryKind
    category: SupplyOrderLineCategory | None = None


@beartype
def classify_supply_order_product(
    facts: SupplyOrderCategoryProductFacts,
    *,
    snacks_folder_id: str,
    ready_meals_folder_id: str,
    shelf_life_days_threshold: int,
) -> SupplyOrderCategoryClassifyResult:
    ancestors = {item.strip().lower() for item in facts.folder_ancestor_ids if item.strip()}
    snacks = snacks_folder_id.strip().lower()
    ready = ready_meals_folder_id.strip().lower()
    in_snacks = bool(snacks) and snacks in ancestors
    in_ready = bool(ready) and ready in ancestors
    if in_snacks:
        return SupplyOrderCategoryClassifyResult(kind="snack")
    if in_ready:
        days = facts.shelf_life_days
        if days is None or days < 0:
            return SupplyOrderCategoryClassifyResult(kind="missing_days")
        if days <= shelf_life_days_threshold:
            return SupplyOrderCategoryClassifyResult(kind="ready_3", category=3)
        return SupplyOrderCategoryClassifyResult(kind="ready_2", category=2)
    return SupplyOrderCategoryClassifyResult(kind="ignore")


@beartype
def index_category_facts(
    rows: Sequence[SupplyOrderCategoryProductFacts],
) -> Mapping[str, SupplyOrderCategoryProductFacts]:
    return {row.catalog_code: row for row in rows}
