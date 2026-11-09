from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.loading_policy import DefaultMatrixCellLoadingPolicy
from src.application.snack_loading.loading_plan import (
    SnackLoadingCellInput,
    compute_snack_loading_plan,
)

_MACHINE = "501"
_POLICY = DefaultMatrixCellLoadingPolicy()


def _cell(
    *,
    line: int = 1,
    product: str = "SKU1",
    capacity: int = 10,
    current: str = "0",
    desired: str | None = "SKU1",
    snapshot: str | None = "SKU1",
    is_food: bool = False,
    matrix: str = "SnackA",
) -> SnackLoadingCellInput:
    return SnackLoadingCellInput(
        machine_code=_MACHINE,
        logical_matrix_name=matrix,
        line_number=line,
        product_code=product,
        capacity=capacity,
        current_qty=Decimal(current),
        desired_product=desired,
        snapshot_product=snapshot,
        is_food=is_food,
    )


def test_plan_full_to_capacity_ships_needed() -> None:
    main = {"SKU1": Decimal("100")}
    plan = compute_snack_loading_plan(
        machine_code=_MACHINE,
        strategy="full_to_capacity",
        cells=(_cell(capacity=10, current="3"),),
        main_available=main,
        min_move_fraction=0.01,
        loading_policy=_POLICY,
    )

    assert len(plan.positions) == 1
    assert plan.positions[0].product_code == "SKU1"
    assert plan.positions[0].quantity == Decimal("7")
    assert plan.lines[0].final_shipped == Decimal("7")
    assert plan.lines[0].needed == Decimal("7")
    assert main["SKU1"] == Decimal("93")


def test_plan_excludes_pending_product_swap_cell() -> None:
    main = {"NEW": Decimal("50"), "OLD": Decimal("50"), "SKU2": Decimal("50")}
    plan = compute_snack_loading_plan(
        machine_code=_MACHINE,
        strategy="full_to_capacity",
        cells=(
            _cell(
                line=1,
                product="OLD",
                capacity=10,
                current="0",
                desired="NEW",
                snapshot="OLD",
            ),
            _cell(
                line=2,
                product="SKU2",
                capacity=5,
                current="0",
                desired="SKU2",
                snapshot="SKU2",
            ),
        ),
        main_available=main,
        min_move_fraction=0.01,
        loading_policy=_POLICY,
    )

    product_codes = {p.product_code for p in plan.positions}
    assert "NEW" not in product_codes
    assert "OLD" not in product_codes
    assert product_codes == {"SKU2"}
    assert any(b.line_number == 1 for b in plan.blocked_by_loading_policy)


def test_plan_uses_snapshot_capacity() -> None:
    main = {"SKU1": Decimal("100")}
    plan = compute_snack_loading_plan(
        machine_code=_MACHINE,
        strategy="full_to_capacity",
        cells=(_cell(capacity=10, current="0"),),
        main_available=main,
        min_move_fraction=0.01,
        loading_policy=_POLICY,
    )

    assert plan.lines[0].target_qty == 10
    assert plan.positions[0].quantity == Decimal("10")


def test_plan_food_ships_one() -> None:
    main = {"FOOD": Decimal("0")}
    plan = compute_snack_loading_plan(
        machine_code=_MACHINE,
        strategy="full_to_capacity",
        cells=(
            _cell(
                product="FOOD",
                capacity=50,
                current="0",
                desired="FOOD",
                snapshot="FOOD",
                is_food=True,
            ),
        ),
        main_available=main,
        min_move_fraction=0.99,
        loading_policy=_POLICY,
        handle_food_products=True,
    )

    assert len(plan.positions) == 1
    assert plan.positions[0].quantity == Decimal("1")
    assert main["FOOD"] == Decimal("-1")
    assert plan.shortages and plan.shortages[0].shortage_qty == Decimal("1")


def test_plan_skips_below_min_move_fraction() -> None:
    main = {"SKU1": Decimal("100")}
    plan = compute_snack_loading_plan(
        machine_code=_MACHINE,
        strategy="full_to_capacity",
        cells=(_cell(capacity=100, current="99"),),
        main_available=main,
        min_move_fraction=0.15,
        loading_policy=_POLICY,
    )

    assert not plan.positions
    assert main["SKU1"] == Decimal("100")
    assert plan.skipped_small_moves
