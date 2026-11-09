from __future__ import annotations

from src.application.matrix_automation.sheets.layout import (
    AUTO_SYNC_COL,
    AUTO_SYNC_ROW,
    BLOCK_COL_STEP,
    BLOCK_ROW_STEP,
    DEFAULT_MATRIX_CATALOG_LAYOUT,
    MACHINE_CODES_COL,
    MATRIX_MULTIPLIER_COL,
    MatrixCatalogLayout,
)


def test_default_layout_matches_block_template_indices() -> None:
    layout = DEFAULT_MATRIX_CATALOG_LAYOUT
    assert layout.machine_codes_col == MACHINE_CODES_COL == 7
    assert layout.matrix_multiplier_col == MATRIX_MULTIPLIER_COL == 49
    assert layout.auto_sync_row == AUTO_SYNC_ROW
    assert layout.auto_sync_col == AUTO_SYNC_COL == 63
    assert layout.product_name_row == 2
    assert layout.line_number_row == 3
    assert layout.block_col_step == BLOCK_COL_STEP == 7
    assert layout.block_row_step == BLOCK_ROW_STEP == 3
    assert isinstance(layout, MatrixCatalogLayout)
