from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from beartype import beartype

SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT = 6
SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF = 10
SNACK_PLANOGRAM_MIN_SHELF_COUNT = 1
SNACK_PLANOGRAM_MIN_SLOTS_PER_SHELF = 1
SNACK_PLANOGRAM_MAX_SHELF_COUNT = 20
SNACK_PLANOGRAM_MAX_SLOTS_PER_SHELF = 20


class PlanogramValidationError(Exception):
    @beartype
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@beartype
@dataclass(frozen=True, slots=True)
class SnackPlanogramMerge:
    shelf_index: int
    slot_index: int


@beartype
@dataclass(frozen=True, slots=True)
class PlanogramAnchorCell:
    shelf_index: int
    slot_index: int
    line_number: int | None
    product_code: str | None
    domain_product_id: str | None = None


@beartype
def default_planogram_dimensions() -> tuple[int, int]:
    return SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT, SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF


@beartype
def validate_planogram(
    *,
    shelf_count: int,
    slots_per_shelf: int,
    merges: tuple[SnackPlanogramMerge, ...],
) -> None:
    if not (
        SNACK_PLANOGRAM_MIN_SHELF_COUNT <= shelf_count <= SNACK_PLANOGRAM_MAX_SHELF_COUNT
        and SNACK_PLANOGRAM_MIN_SLOTS_PER_SHELF
        <= slots_per_shelf
        <= SNACK_PLANOGRAM_MAX_SLOTS_PER_SHELF
    ):
        raise PlanogramValidationError(
            f"invalid planogram dimensions {shelf_count}x{slots_per_shelf}",
            code="invalid_planogram_dimensions",
        )

    spans_by_shelf: dict[int, list[tuple[int, int]]] = {}
    for merge in merges:
        if merge.shelf_index < 0 or merge.shelf_index >= shelf_count:
            raise PlanogramValidationError(
                f"merge shelf_index {merge.shelf_index} out of bounds",
                code="invalid_merge_anchor",
            )
        if merge.slot_index % 2 != 0:
            raise PlanogramValidationError(
                f"merge slot_index {merge.slot_index} must be even",
                code="invalid_merge_anchor",
            )
        if merge.slot_index + 1 >= slots_per_shelf:
            raise PlanogramValidationError(
                f"merge slot_index {merge.slot_index} has no right neighbor",
                code="invalid_merge_anchor",
            )
        span = (merge.slot_index, merge.slot_index + 1)
        for existing_start, existing_end in spans_by_shelf.get(merge.shelf_index, []):
            if not (span[1] < existing_start or span[0] > existing_end):
                raise PlanogramValidationError(
                    f"overlapping merges on shelf {merge.shelf_index}",
                    code="overlapping_merge",
                )
        spans_by_shelf.setdefault(merge.shelf_index, []).append(span)


@beartype
def _anchor_has_data(anchor: PlanogramAnchorCell) -> bool:
    return (
        anchor.line_number is not None
        or anchor.product_code is not None
        or bool((anchor.domain_product_id or "").strip())
    )


@beartype
def validate_planogram_shrink(
    *,
    old_shelf_count: int,
    old_slots_per_shelf: int,
    new_shelf_count: int,
    new_slots_per_shelf: int,
    anchors: tuple[PlanogramAnchorCell, ...],
) -> None:
    for anchor in anchors:
        if (
            anchor.shelf_index >= new_shelf_count or anchor.slot_index >= new_slots_per_shelf
        ) and _anchor_has_data(anchor):
            raise PlanogramValidationError(
                f"anchor ({anchor.shelf_index}, {anchor.slot_index}) outside new bounds",
                code="planogram_shrink_blocked",
            )


@beartype
def filter_merges_in_bounds(
    merges: tuple[SnackPlanogramMerge, ...],
    *,
    shelf_count: int,
    slots_per_shelf: int,
) -> tuple[SnackPlanogramMerge, ...]:
    return tuple(
        merge
        for merge in merges
        if 0 <= merge.shelf_index < shelf_count
        and 0 <= merge.slot_index < slots_per_shelf
        and merge.slot_index + 1 < slots_per_shelf
    )


@beartype
def absorbed_merge_slots(
    merges: tuple[SnackPlanogramMerge, ...],
) -> frozenset[tuple[int, int]]:
    return frozenset((merge.shelf_index, merge.slot_index + 1) for merge in merges)


@beartype
def drop_absorbed_merge_anchors(
    anchors: tuple[PlanogramAnchorCell, ...],
    merges: tuple[SnackPlanogramMerge, ...],
) -> tuple[PlanogramAnchorCell, ...]:
    absorbed = absorbed_merge_slots(merges)
    return tuple(
        anchor for anchor in anchors if (anchor.shelf_index, anchor.slot_index) not in absorbed
    )


@beartype
def project_planogram_cells(
    *,
    anchors: tuple[PlanogramAnchorCell, ...],
) -> tuple[Any, ...]:
    from src.application.matrix_automation.snack_machine_layout import SnackMachineLayoutCell

    cells: list[SnackMachineLayoutCell] = []
    seen_lines: set[int] = set()
    seen_slots: set[tuple[int, int]] = set()
    for anchor in anchors:
        domain_id = (anchor.domain_product_id or "").strip() or None
        if anchor.product_code is None and domain_id is None:
            continue
        if anchor.line_number is None:
            continue
        if anchor.line_number < 1:
            raise PlanogramValidationError(
                f"invalid line_number {anchor.line_number}",
                code="invalid_line_number",
            )
        if anchor.line_number in seen_lines:
            raise PlanogramValidationError(
                f"duplicate line_number {anchor.line_number}",
                code="duplicate_line_number",
            )
        seen_lines.add(anchor.line_number)
        slot_key = (anchor.shelf_index, anchor.slot_index)
        if slot_key in seen_slots:
            raise PlanogramValidationError(
                f"duplicate planogram slot {slot_key}",
                code="duplicate_planogram_slot",
            )
        seen_slots.add(slot_key)
        product_code = None if domain_id is not None else anchor.product_code
        cells.append(
            SnackMachineLayoutCell(
                line_number=anchor.line_number,
                product_code=product_code,
                shelf_index=anchor.shelf_index,
                slot_index=anchor.slot_index,
                domain_product_id=domain_id,
            ),
        )
    return tuple(cells)
