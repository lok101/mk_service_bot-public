from __future__ import annotations

from dataclasses import dataclass

# Header (1-based Sheets → 0-based indices): H1, AX1, BL1
MACHINE_CODES_ROW = 0
MACHINE_CODES_COL = 7
MATRIX_MULTIPLIER_ROW = 0
MATRIX_MULTIPLIER_COL = 49
AUTO_SYNC_ROW = 0
AUTO_SYNC_COL = 63

# Product blocks: A3/H3/O3/… and A4/H4/O4/… (step 7);
# vertical bands every 3 rows (name, line number, spacer)
PRODUCT_NAME_ROW = 2
LINE_NUMBER_ROW = 3
BLOCK_START_COL = 0
BLOCK_COL_STEP = 7
BLOCK_ROW_STEP = 3


@dataclass(frozen=True, slots=True)
class MatrixCatalogLayout:
    machine_codes_row: int = MACHINE_CODES_ROW
    machine_codes_col: int = MACHINE_CODES_COL
    auto_sync_row: int = AUTO_SYNC_ROW
    auto_sync_col: int = AUTO_SYNC_COL
    matrix_multiplier_row: int = MATRIX_MULTIPLIER_ROW
    matrix_multiplier_col: int = MATRIX_MULTIPLIER_COL
    product_name_row: int = PRODUCT_NAME_ROW
    line_number_row: int = LINE_NUMBER_ROW
    block_start_col: int = BLOCK_START_COL
    block_col_step: int = BLOCK_COL_STEP
    block_row_step: int = BLOCK_ROW_STEP


DEFAULT_MATRIX_CATALOG_LAYOUT = MatrixCatalogLayout()
