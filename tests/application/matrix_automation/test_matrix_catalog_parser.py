from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.matrix_automation.models import ProductBlock
from src.application.matrix_automation.sheets.layout import (
    AUTO_SYNC_COL,
    BLOCK_COL_STEP,
    BLOCK_ROW_STEP,
    LINE_NUMBER_ROW,
    MACHINE_CODES_COL,
    MATRIX_MULTIPLIER_COL,
    PRODUCT_NAME_ROW,
    MatrixCatalogLayout,
)
from src.application.matrix_automation.sheets.matrix_catalog import parse_matrix_catalog_tab

_HEADER_WIDTH = AUTO_SYNC_COL + 1

_PARSE_KW = dict(
    logical_matrix_name="Snacks",
    name_to_code={
        "A": "MS-A",
        "B": "MS-B",
        "C": "MS-C",
        "D": "MS-D",
    },
    product_block_map={},
    matrix_multiplier_min=Decimal("0.8"),
    matrix_multiplier_max=Decimal("3.0"),
)


def _enabled_tab(
    *,
    auto_sync: str = "TRUE",
    multiplier: str = "1.0",
    machines: str = "512",
    blocks: tuple[tuple[int, str, str], ...] = ((0, "1", "Кола 0.5"), (BLOCK_COL_STEP, "2", "")),
) -> list[list[str]]:
    header = [""] * _HEADER_WIDTH
    header[MACHINE_CODES_COL] = machines
    header[MATRIX_MULTIPLIER_COL] = multiplier
    header[AUTO_SYNC_COL] = auto_sync
    max_col = max((col for col, _, _ in blocks), default=0) + 1
    width = max(_HEADER_WIDTH, max_col)
    product_row = [""] * width
    line_row = [""] * width
    for col, line, name in blocks:
        product_row[col] = name
        line_row[col] = line
    return [header, [], product_row, line_row]


def _multi_band_tab(
    *,
    bands: tuple[tuple[tuple[int, str, str], ...], ...],
    auto_sync: str = "TRUE",
    multiplier: str = "1.0",
    machines: str = "512",
) -> list[list[str]]:
    """bands[k] = blocks for band k: (col, line_number_str, product_name)."""
    header = [""] * _HEADER_WIDTH
    header[MACHINE_CODES_COL] = machines
    header[MATRIX_MULTIPLIER_COL] = multiplier
    header[AUTO_SYNC_COL] = auto_sync
    max_col = (
        max(
            (col for band in bands for col, _, _ in band),
            default=0,
        )
        + 1
    )
    width = max(_HEADER_WIDTH, max_col)
    band_count = len(bands)
    last_line_row = LINE_NUMBER_ROW + (band_count - 1) * BLOCK_ROW_STEP
    rows: list[list[str]] = [[""] * width for _ in range(last_line_row + 1)]
    rows[0] = header
    for k, band in enumerate(bands):
        name_row = PRODUCT_NAME_ROW + k * BLOCK_ROW_STEP
        line_row = LINE_NUMBER_ROW + k * BLOCK_ROW_STEP
        for col, line, name in band:
            rows[name_row][col] = name
            rows[line_row][col] = line
    return rows


def test_parse_matrix_catalog_tab_uses_canon_decimal_parser() -> None:
    rows = _enabled_tab(
        multiplier="1,25",
        blocks=((0, "1", "A"), (BLOCK_COL_STEP, "2", "")),
    )
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    assert result.enabled.matrix_multiplier == Decimal("1.25")


def test_enabled_matrix_parses_machines_and_multiplier() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(multiplier="1,5", machines="514"),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.auto_sync_disabled is False
    assert result.blocked is None
    assert result.enabled is not None
    assert result.enabled.logical_matrix_name == "Snacks"
    assert result.enabled.machine_codes == ("514",)
    assert result.enabled.matrix_multiplier == Decimal("1.5")
    assert len(result.enabled.cells) == 2
    assert result.enabled.cells[0].line_number == 1
    assert result.enabled.cells[0].product_code == "MS-1"
    assert result.enabled.cells[1].line_number == 2
    assert result.enabled.cells[1].product_code is None


def test_bracket_and_comma_separated_machine_codes() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(machines="[512], 514"),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.enabled is not None
    assert result.enabled.machine_codes == ("512", "514")


def test_name_without_black_line_number_is_skipped() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(blocks=((0, "", "Кола 0.5"), (BLOCK_COL_STEP, "2", "Чипсы"))),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1", "Чипсы": "MS-2"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.enabled is not None
    assert len(result.enabled.cells) == 1
    assert result.enabled.cells[0].line_number == 2
    assert result.enabled.cells[0].product_code == "MS-2"


def test_invalid_matrix_multiplier_blocks_matrix() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(multiplier="10"),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.enabled is None
    assert result.blocked is not None
    assert result.blocked.deploy_reason == "invalid_matrix_multiplier"


def test_no_machines_blocks_matrix() -> None:
    header = [""] * _HEADER_WIDTH
    header[MATRIX_MULTIPLIER_COL] = "1.0"
    header[AUTO_SYNC_COL] = "TRUE"
    rows = [header, [], ["Кола 0.5"], ["1"]]
    result = parse_matrix_catalog_tab(
        rows,
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.blocked is not None
    assert result.blocked.deploy_reason == "invalid_matrix_header"
    assert "no_machines" in result.blocked.detail


def test_disabled_matrix_increments_auto_sync_disabled() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(auto_sync="FALSE"),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.auto_sync_disabled is True
    assert result.enabled is None
    assert result.blocked is None


def test_disabled_matrix_incomplete_header_does_not_block() -> None:
    header = [""] * _HEADER_WIDTH
    header[MATRIX_MULTIPLIER_COL] = "10"
    header[AUTO_SYNC_COL] = "FALSE"
    rows = [header, [], ["Кола 0.5"], ["1"]]
    result = parse_matrix_catalog_tab(
        rows,
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.auto_sync_disabled is True
    assert result.enabled is None
    assert result.blocked is None


def test_unknown_product_name_blocks_matrix() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(),
        logical_matrix_name="Snacks",
        name_to_code={},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.blocked is not None
    assert result.blocked.deploy_reason == "unknown_product_name"
    assert len(result.blocked.products) == 1


def test_product_block_by_code_blocks_matrix() -> None:
    block = ProductBlock(
        product_name="Кола 0.5",
        product_code="MS-1",
        detail="duplicate_product_multiplier: MS-1",
    )
    result = parse_matrix_catalog_tab(
        _enabled_tab(),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={"MS-1": block},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.enabled is None
    assert result.blocked is not None
    assert result.blocked.deploy_reason == "product_reference_invalid"
    assert "duplicate_product_multiplier: MS-1" in result.blocked.detail
    assert len(result.blocked.products) == 1
    assert result.blocked.products[0].product_code == "MS-1"


def test_invalid_machine_code_blocks_matrix() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(machines="битый"),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.blocked is not None
    assert result.blocked.deploy_reason == "invalid_matrix_header"
    assert "invalid_machine_code" in result.blocked.detail


def test_duplicate_machine_code_blocks_matrix() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(machines="512, 512"),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.blocked is not None
    assert "duplicate_machine_code" in result.blocked.detail


def test_duplicate_line_number_blocks_matrix() -> None:
    result = parse_matrix_catalog_tab(
        _enabled_tab(
            blocks=(
                (0, "1", "Кола 0.5"),
                (BLOCK_COL_STEP, "1", "Другой"),
            ),
        ),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1", "Другой": "MS-2"},
        product_block_map={},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.blocked is not None
    assert "duplicate_line_number" in result.blocked.detail


def test_product_block_by_name_fills_detail_and_products() -> None:
    block = ProductBlock(
        product_name="Кола 0.5",
        product_code="MS-1",
        detail="duplicate_product_name: Кола 0.5",
    )
    result = parse_matrix_catalog_tab(
        _enabled_tab(),
        logical_matrix_name="Snacks",
        name_to_code={"Кола 0.5": "MS-1"},
        product_block_map={"Кола 0.5": block},
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )
    assert result.blocked is not None
    assert "duplicate_product_name: Кола 0.5" in result.blocked.detail
    assert len(result.blocked.products) == 1
    assert result.blocked.products[0].product_name == "Кола 0.5"


def test_multi_band_parses_cells_from_all_bands() -> None:
    # happy: две полосы step 3
    rows = _multi_band_tab(
        bands=(
            ((0, "1", "A"), (BLOCK_COL_STEP, "2", "B")),
            ((0, "11", "C"), (BLOCK_COL_STEP, "12", "D")),
        ),
    )
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    lines = [c.line_number for c in result.enabled.cells]
    assert lines == [1, 2, 11, 12]


def test_last_band_without_trailing_spacer_is_parsed() -> None:
    # happy: line_row = последняя строка rows
    rows = _multi_band_tab(bands=(((0, "51", "A"),),))
    assert len(rows) == 4  # header..line_row inclusive; no spacer
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    assert [c.line_number for c in result.enabled.cells] == [51]


def test_empty_band_hard_stops_even_if_later_band_has_numbers() -> None:
    # edge: дыра → hard-stop
    rows = _multi_band_tab(
        bands=(
            ((0, "1", "A"),),
            (),  # empty band k=1
            ((0, "31", "C"),),
        ),
    )
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    assert [c.line_number for c in result.enabled.cells] == [1]


def test_non_int_line_token_does_not_keep_band_alive() -> None:
    # edge: только мусор в номерной строке → hard-stop (полоса пустая)
    rows = _multi_band_tab(
        bands=(
            ((0, "1", "A"),),
            ((0, "нет", "B"),),
            ((0, "31", "C"),),
        ),
    )
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    assert [c.line_number for c in result.enabled.cells] == [1]


def test_duplicate_line_number_across_bands_blocks_matrix() -> None:
    # error
    rows = _multi_band_tab(
        bands=(
            ((0, "1", "A"),),
            ((0, "1", "B"),),
        ),
    )
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is None
    assert result.blocked is not None
    assert result.blocked.deploy_reason == "invalid_matrix_header"
    assert "duplicate_line_number: 1" in result.blocked.detail


def test_wide_band_skips_columns_without_line_number() -> None:
    # edge: в полосе только col=0; col=7 пуст — skip; вторая полоса col=0 → 11
    rows = _multi_band_tab(
        bands=(
            ((0, "1", "A"),),
            ((0, "11", "C"),),
        ),
    )
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    assert [c.line_number for c in result.enabled.cells] == [1, 11]


def test_block_row_step_less_than_one_raises() -> None:
    layout = MatrixCatalogLayout(block_row_step=0)
    with pytest.raises(ValueError, match="block_row_step must be >= 1"):
        parse_matrix_catalog_tab(
            _enabled_tab(),
            layout=layout,
            logical_matrix_name="Snacks",
            name_to_code={"Кола 0.5": "MS-1"},
            product_block_map={},
            matrix_multiplier_min=Decimal("0.8"),
            matrix_multiplier_max=Decimal("3.0"),
        )


def test_empty_first_band_yields_no_cells() -> None:
    # edge: k=0 без успешных int → hard-stop сразу; шапка валидна
    rows = _multi_band_tab(bands=((),))
    result = parse_matrix_catalog_tab(rows, **_PARSE_KW)
    assert result.enabled is not None
    assert result.enabled.cells == ()
