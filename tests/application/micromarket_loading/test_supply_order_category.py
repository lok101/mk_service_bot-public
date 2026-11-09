from __future__ import annotations

from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryProductFacts,
    classify_supply_order_product,
)

_SNACKS = "4c2738f1-f43a-11ef-0a80-1a2b002150a4"
_READY = "7203a901-b1b2-11f1-0a80-115a00344501"


def _facts(
    *,
    ancestors: tuple[str, ...],
    days: int | None,
    code: str = "ms-1",
) -> SupplyOrderCategoryProductFacts:
    return SupplyOrderCategoryProductFacts(
        catalog_code=code,
        folder_ancestor_ids=ancestors,
        shelf_life_days=days,
    )


def test_snacks_folder_is_snack_regardless_of_days() -> None:
    result = classify_supply_order_product(
        _facts(ancestors=(_SNACKS, "parent"), days=3),
        snacks_folder_id=_SNACKS,
        ready_meals_folder_id=_READY,
        shelf_life_days_threshold=7,
    )
    assert result.kind == "snack"
    assert result.category is None


def test_ready_meals_le_threshold_is_cat3() -> None:
    result = classify_supply_order_product(
        _facts(ancestors=("child", _READY), days=7),
        snacks_folder_id=_SNACKS,
        ready_meals_folder_id=_READY,
        shelf_life_days_threshold=7,
    )
    assert result.kind == "ready_3"
    assert result.category == 3


def test_ready_meals_gt_threshold_is_cat2() -> None:
    result = classify_supply_order_product(
        _facts(ancestors=(_READY,), days=8),
        snacks_folder_id=_SNACKS,
        ready_meals_folder_id=_READY,
        shelf_life_days_threshold=7,
    )
    assert result.kind == "ready_2"
    assert result.category == 2


def test_ready_meals_missing_days_blocks() -> None:
    result = classify_supply_order_product(
        _facts(ancestors=(_READY,), days=None),
        snacks_folder_id=_SNACKS,
        ready_meals_folder_id=_READY,
        shelf_life_days_threshold=7,
    )
    assert result.kind == "missing_days"
    assert result.category is None


def test_outside_branches_is_ignore() -> None:
    result = classify_supply_order_product(
        _facts(ancestors=("other-folder",), days=2),
        snacks_folder_id=_SNACKS,
        ready_meals_folder_id=_READY,
        shelf_life_days_threshold=7,
    )
    assert result.kind == "ignore"
