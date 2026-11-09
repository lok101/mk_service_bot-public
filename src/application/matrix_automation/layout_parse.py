from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype

from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
)
from src.application.matrix_automation.snack_machine_layout import SnackMachineLayout


@beartype
def layouts_to_parse_state(layouts: Sequence[SnackMachineLayout]) -> MatrixParseState:
    enabled: list[EnabledLogicalMatrix] = []
    auto_sync_disabled = 0
    for layout in layouts:
        if not layout.auto_sync_enabled:
            auto_sync_disabled += 1
            continue
        enabled.append(enabled_matrix_from_layout(layout))
    return MatrixParseState(
        enabled_matrices=tuple(enabled),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=auto_sync_disabled,
    )


@beartype
def enabled_matrix_from_layout(layout: SnackMachineLayout) -> EnabledLogicalMatrix:
    return EnabledLogicalMatrix(
        logical_matrix_name=layout.logical_matrix_name,
        machine_codes=(layout.machine_code,),
        matrix_multiplier=layout.matrix_multiplier,
        cells=tuple(
            MatrixCatalogCell(
                line_number=cell.line_number,
                product_name=cell.product_code or "",
                product_code=cell.product_code,
            )
            for cell in layout.cells
        ),
    )
