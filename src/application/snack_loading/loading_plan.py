from __future__ import annotations

import math
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.matrix_automation.ports import MatrixCellLoadingPolicy
from src.domain.snack_loading.events import CellKey

LoadingStrategy = Literal["full_to_capacity", "to_percent"]
ApparatusStockAnomalyKind = Literal["negative", "over_capacity"]


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingCellInput:
    machine_code: str
    logical_matrix_name: str
    line_number: int
    product_code: str
    capacity: int
    current_qty: Decimal
    desired_product: str | None
    snapshot_product: str | None
    is_food: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingPlanLine:
    cell_key: CellKey
    product_code: str
    needed: Decimal
    shipped: Decimal
    final_shipped: Decimal
    target_qty: int


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingMovePosition:
    product_code: str
    quantity: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class ShortageReport:
    machine_code: str
    product_code: str
    needed_qty: Decimal
    available_on_main_qty: Decimal
    shortage_qty: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class SkippedSmallMoveReport:
    machine_code: str
    product_code: str
    total_capacity: int
    min_move_fraction: float
    threshold_qty: Decimal
    shipped_before_threshold: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class ApparatusStockAnomalyReport:
    machine_code: str
    product_code: str
    kind: ApparatusStockAnomalyKind
    current_qty: Decimal
    total_capacity: int


@beartype
@dataclass(frozen=True, slots=True)
class BlockedByLoadingPolicyCell:
    machine_code: str
    logical_matrix_name: str
    line_number: int
    desired_product: str | None
    snapshot_product: str | None


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingPlan:
    lines: tuple[SnackLoadingPlanLine, ...]
    positions: tuple[SnackLoadingMovePosition, ...]
    shortages: tuple[ShortageReport, ...]
    skipped_small_moves: tuple[SkippedSmallMoveReport, ...]
    anomalies: tuple[ApparatusStockAnomalyReport, ...]
    blocked_by_loading_policy: tuple[BlockedByLoadingPolicyCell, ...]


def _strategy_factor(*, strategy: LoadingStrategy, percent: int | None) -> float:
    if strategy == "full_to_capacity":
        return 1.0
    if percent is None:
        msg = "percent is required for to_percent strategy"
        raise ValueError(msg)
    return percent / 100.0


@beartype
def compute_snack_loading_plan(
    *,
    machine_code: str,
    strategy: LoadingStrategy,
    cells: Sequence[SnackLoadingCellInput],
    main_available: MutableMapping[str, Decimal],
    min_move_fraction: float,
    loading_policy: MatrixCellLoadingPolicy,
    percent: int | None = None,
    handle_food_products: bool = True,
) -> SnackLoadingPlan:
    """Compute per-cell loading plan; mutate ``main_available`` by ``final_shipped``.

    Pending product-swap cells are excluded via ``loading_policy``. Food cells ship
    exactly 1 when ``handle_food_products`` is True (bypass main stock and min fraction).
    """
    factor = _strategy_factor(strategy=strategy, percent=percent)
    lines_out: list[SnackLoadingPlanLine] = []
    position_qty: dict[str, Decimal] = {}
    shortages: list[ShortageReport] = []
    skipped: list[SkippedSmallMoveReport] = []
    anomalies: list[ApparatusStockAnomalyReport] = []
    blocked: list[BlockedByLoadingPolicyCell] = []

    for cell in cells:
        cell_key: CellKey = (cell.machine_code, cell.logical_matrix_name, cell.line_number)
        if loading_policy.is_loading_blocked(
            desired_product=cell.desired_product,
            snapshot_product=cell.snapshot_product,
        ):
            blocked.append(
                BlockedByLoadingPolicyCell(
                    machine_code=cell.machine_code,
                    logical_matrix_name=cell.logical_matrix_name,
                    line_number=cell.line_number,
                    desired_product=cell.desired_product,
                    snapshot_product=cell.snapshot_product,
                )
            )
            continue

        if cell.is_food and not handle_food_products:
            continue

        raw_qty = cell.current_qty
        if raw_qty < 0:
            anomalies.append(
                ApparatusStockAnomalyReport(
                    machine_code=machine_code,
                    product_code=cell.product_code,
                    kind="negative",
                    current_qty=raw_qty,
                    total_capacity=cell.capacity,
                )
            )
        if raw_qty > cell.capacity:
            anomalies.append(
                ApparatusStockAnomalyReport(
                    machine_code=machine_code,
                    product_code=cell.product_code,
                    kind="over_capacity",
                    current_qty=raw_qty,
                    total_capacity=cell.capacity,
                )
            )

        if cell.is_food and handle_food_products:
            available_main = max(Decimal("0"), main_available.get(cell.product_code, Decimal("0")))
            if available_main < Decimal("1"):
                shortages.append(
                    ShortageReport(
                        machine_code=machine_code,
                        product_code=cell.product_code,
                        needed_qty=Decimal("1"),
                        available_on_main_qty=available_main,
                        shortage_qty=Decimal("1") - available_main,
                    )
                )
            lines_out.append(
                SnackLoadingPlanLine(
                    cell_key=cell_key,
                    product_code=cell.product_code,
                    needed=Decimal("1"),
                    shipped=Decimal("1"),
                    final_shipped=Decimal("1"),
                    target_qty=1,
                )
            )
            main_available[cell.product_code] = main_available.get(
                cell.product_code, Decimal("0")
            ) - Decimal("1")
            position_qty[cell.product_code] = position_qty.get(
                cell.product_code, Decimal("0")
            ) + Decimal("1")
            continue

        effective_current = max(raw_qty, Decimal("0"))
        target_qty = int(math.floor(cell.capacity * factor))
        needed = max(Decimal("0"), Decimal(target_qty) - effective_current)
        available_main = max(Decimal("0"), main_available.get(cell.product_code, Decimal("0")))
        shipped = min(needed, available_main)

        if needed > available_main and needed > 0:
            shortages.append(
                ShortageReport(
                    machine_code=machine_code,
                    product_code=cell.product_code,
                    needed_qty=needed,
                    available_on_main_qty=available_main,
                    shortage_qty=needed - available_main,
                )
            )

        if shipped <= 0:
            continue

        threshold_qty = Decimal(str(cell.capacity)) * Decimal(str(min_move_fraction))
        if threshold_qty > shipped:
            skipped.append(
                SkippedSmallMoveReport(
                    machine_code=machine_code,
                    product_code=cell.product_code,
                    total_capacity=cell.capacity,
                    min_move_fraction=min_move_fraction,
                    threshold_qty=threshold_qty,
                    shipped_before_threshold=shipped,
                )
            )
            final_shipped = Decimal("0")
        else:
            final_shipped = shipped

        lines_out.append(
            SnackLoadingPlanLine(
                cell_key=cell_key,
                product_code=cell.product_code,
                needed=needed,
                shipped=shipped,
                final_shipped=final_shipped,
                target_qty=target_qty,
            )
        )

        if final_shipped > 0:
            prev = main_available.get(cell.product_code, Decimal("0"))
            main_available[cell.product_code] = max(Decimal("0"), prev - final_shipped)
            position_qty[cell.product_code] = (
                position_qty.get(cell.product_code, Decimal("0")) + final_shipped
            )

    positions = tuple(
        SnackLoadingMovePosition(product_code=code, quantity=qty)
        for code, qty in sorted(position_qty.items())
        if qty > 0
    )
    return SnackLoadingPlan(
        lines=tuple(lines_out),
        positions=positions,
        shortages=tuple(shortages),
        skipped_small_moves=tuple(skipped),
        anomalies=tuple(anomalies),
        blocked_by_loading_policy=tuple(blocked),
    )
