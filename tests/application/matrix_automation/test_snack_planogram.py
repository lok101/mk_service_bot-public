from __future__ import annotations

import pytest

from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_planogram import (
    SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT,
    SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF,
    PlanogramAnchorCell,
    PlanogramValidationError,
    SnackPlanogramMerge,
    default_planogram_dimensions,
    project_planogram_cells,
    validate_planogram,
    validate_planogram_shrink,
)


def test_snack_machine_layout_cell_accepts_optional_coords() -> None:
    legacy = SnackMachineLayoutCell(line_number=1, product_code="A")
    sticky = SnackMachineLayoutCell(
        line_number=19,
        product_code="AQUA_GAS",
        shelf_index=0,
        slot_index=7,
    )
    assert legacy.shelf_index is None
    assert legacy.slot_index is None
    assert sticky.shelf_index == 0
    assert sticky.slot_index == 7


def test_default_planogram_dimensions_are_6x10() -> None:
    shelf_count, slots_per_shelf = default_planogram_dimensions()
    assert shelf_count == SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT == 6
    assert slots_per_shelf == SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF == 10


def test_snack_machine_layout_defaults_planogram_when_omitted() -> None:
    layout = SnackMachineLayout(
        machine_code="512",
        logical_matrix_name="512",
        matrix_multiplier=__import__("decimal").Decimal("1"),
        auto_sync_enabled=True,
        cells=(),
    )
    assert layout.shelf_count == 6
    assert layout.slots_per_shelf == 10
    assert layout.merges == ()


def test_validate_planogram_accepts_even_merge_anchor() -> None:
    validate_planogram(
        shelf_count=6,
        slots_per_shelf=10,
        merges=(SnackPlanogramMerge(shelf_index=4, slot_index=0),),
    )


def test_validate_planogram_rejects_odd_merge_anchor() -> None:
    with pytest.raises(PlanogramValidationError) as exc:
        validate_planogram(
            shelf_count=6,
            slots_per_shelf=10,
            merges=(SnackPlanogramMerge(shelf_index=0, slot_index=1),),
        )
    assert exc.value.code == "invalid_merge_anchor"


def test_validate_planogram_rejects_overlapping_merges() -> None:
    with pytest.raises(PlanogramValidationError) as exc:
        validate_planogram(
            shelf_count=6,
            slots_per_shelf=10,
            merges=(
                SnackPlanogramMerge(shelf_index=0, slot_index=0),
                SnackPlanogramMerge(shelf_index=0, slot_index=0),
            ),
        )
    assert exc.value.code == "overlapping_merge"


def test_validate_planogram_rejects_invalid_dimensions() -> None:
    with pytest.raises(PlanogramValidationError) as exc:
        validate_planogram(shelf_count=0, slots_per_shelf=10, merges=())
    assert exc.value.code == "invalid_planogram_dimensions"


def test_project_planogram_cells_persists_anchor_coords() -> None:
    cells = project_planogram_cells(
        anchors=(
            PlanogramAnchorCell(0, 0, 11, "SKU1"),
            PlanogramAnchorCell(0, 7, 19, "AQUA"),
        ),
    )
    assert cells == (
        SnackMachineLayoutCell(11, "SKU1", 0, 0),
        SnackMachineLayoutCell(19, "AQUA", 0, 7),
    )


def test_project_planogram_cells_keeps_unlinked_domain_product() -> None:
    cells = project_planogram_cells(
        anchors=(
            PlanogramAnchorCell(
                shelf_index=0,
                slot_index=0,
                line_number=1,
                product_code=None,
                domain_product_id="prod-1",
            ),
        )
    )
    assert cells[0].domain_product_id == "prod-1"
    assert cells[0].product_code is None


def test_project_planogram_cells_rejects_duplicate_slot() -> None:
    with pytest.raises(PlanogramValidationError) as exc:
        project_planogram_cells(
            anchors=(
                PlanogramAnchorCell(0, 0, 11, "A"),
                PlanogramAnchorCell(0, 0, 12, "B"),
            ),
        )
    assert exc.value.code == "duplicate_planogram_slot"


def test_project_planogram_cells_omits_empty() -> None:
    cells = project_planogram_cells(
        anchors=(
            PlanogramAnchorCell(0, 0, 11, "SKU1"),
            PlanogramAnchorCell(0, 1, None, None),
        ),
    )
    assert cells == (SnackMachineLayoutCell(11, "SKU1", 0, 0),)


def test_project_planogram_cells_rejects_duplicate_line() -> None:
    with pytest.raises(PlanogramValidationError) as exc:
        project_planogram_cells(
            anchors=(
                PlanogramAnchorCell(0, 0, 11, "A"),
                PlanogramAnchorCell(1, 0, 11, "B"),
            ),
        )
    assert exc.value.code == "duplicate_line_number"


def test_validate_planogram_shrink_blocks_data_outside_bounds() -> None:
    with pytest.raises(PlanogramValidationError) as exc:
        validate_planogram_shrink(
            old_shelf_count=6,
            old_slots_per_shelf=10,
            new_shelf_count=5,
            new_slots_per_shelf=10,
            anchors=(PlanogramAnchorCell(5, 0, 1, "X"),),
        )
    assert exc.value.code == "planogram_shrink_blocked"
