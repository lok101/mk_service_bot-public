from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.deploy_reasons import (
    INVALID_MATRIX_HEADER,
    INVALID_MATRIX_MULTIPLIER,
    PRODUCT_REFERENCE_INVALID,
    UNKNOWN_PRODUCT_NAME,
)
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    BlockedProductRef,
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    ProductBlock,
)
from src.application.matrix_automation.sheets.layout import (
    DEFAULT_MATRIX_CATALOG_LAYOUT,
    MatrixCatalogLayout,
)
from src.application.matrix_automation.sheets.machine_code import parse_sheet_machine_code
from src.application.shared.sheet_cell_format import parse_sheet_decimal
from src.domain.matrix_pricing.product_lookup import resolve_product_code


@beartype
def _product_block_hit(
    *,
    name_raw: str,
    product_code: str | None,
    product_block_map: dict[str, ProductBlock],
) -> ProductBlock | None:
    if name_raw in product_block_map:
        return product_block_map[name_raw]
    if product_code is not None and product_code in product_block_map:
        return product_block_map[product_code]
    return None


@beartype
def _blocked_entry_from_product_hits(
    *,
    logical_matrix_name: str,
    machine_codes: tuple[str, ...],
    hits: tuple[ProductBlock, ...],
) -> BlockedMatrixEntry:
    products = tuple(
        BlockedProductRef(
            product_name=block.product_name or "",
            product_code=block.product_code,
        )
        for block in hits
        if block.product_name or block.product_code
    )
    detail = hits[0].detail if hits else PRODUCT_REFERENCE_INVALID
    if not detail.startswith(PRODUCT_REFERENCE_INVALID):
        detail = f"{PRODUCT_REFERENCE_INVALID}: {detail}"
    return BlockedMatrixEntry(
        logical_matrix_name=logical_matrix_name,
        deploy_reason=PRODUCT_REFERENCE_INVALID,
        detail=detail,
        products=products,
        machine_codes=machine_codes,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MatrixCatalogTabParseResult:
    enabled: EnabledLogicalMatrix | None
    blocked: BlockedMatrixEntry | None
    auto_sync_disabled: bool


@beartype
def _cell(rows: list[list[str]], row: int, col: int) -> str:
    if row >= len(rows):
        return ""
    line = rows[row]
    if col >= len(line):
        return ""
    return line[col].strip()


@beartype
def _parse_bool_checkbox(raw: str) -> bool:
    normalized = raw.strip().upper()
    return normalized in {"TRUE", "1", "YES", "ДА"}


@beartype
def _max_row_width(rows: list[list[str]]) -> int:
    return max((len(row) for row in rows), default=0)


@beartype
def parse_catalog_tab_machine_codes(
    rows: list[list[str]],
    *,
    layout: MatrixCatalogLayout = DEFAULT_MATRIX_CATALOG_LAYOUT,
) -> tuple[str, ...]:
    """Read H1 machine codes without parsing multiplier/cells (no Decimal)."""
    raw = _cell(rows, layout.machine_codes_row, layout.machine_codes_col)
    if not raw:
        return ()
    codes: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        stripped = token.strip()
        if not stripped:
            continue
        code = parse_sheet_machine_code(stripped)
        if code is None:
            msg = f"invalid_machine_code: {stripped}"
            raise ValueError(msg)
        if code in seen:
            msg = f"duplicate_machine_code: {code}"
            raise ValueError(msg)
        seen.add(code)
        codes.append(code)
    return tuple(codes)


@beartype
def _parse_machine_codes(rows: list[list[str]], layout: MatrixCatalogLayout) -> tuple[str, ...]:
    return parse_catalog_tab_machine_codes(rows, layout=layout)


@beartype
def parse_matrix_catalog_tab(
    rows: list[list[str]],
    *,
    logical_matrix_name: str,
    name_to_code: dict[str, str],
    product_block_map: dict[str, ProductBlock],
    matrix_multiplier_min: Decimal,
    matrix_multiplier_max: Decimal,
    layout: MatrixCatalogLayout = DEFAULT_MATRIX_CATALOG_LAYOUT,
) -> MatrixCatalogTabParseResult:
    trimmed_name = logical_matrix_name.strip()
    if not trimmed_name:
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=BlockedMatrixEntry(
                logical_matrix_name=logical_matrix_name,
                deploy_reason=INVALID_MATRIX_HEADER,
                detail=f"{INVALID_MATRIX_HEADER}: invalid_matrix_name",
                products=(),
                machine_codes=(),
            ),
            auto_sync_disabled=False,
        )

    auto_sync_raw = _cell(rows, layout.auto_sync_row, layout.auto_sync_col)
    if not _parse_bool_checkbox(auto_sync_raw):
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=None,
            auto_sync_disabled=True,
        )

    try:
        machine_codes = _parse_machine_codes(rows, layout)
    except ValueError as exc:
        detail = f"{INVALID_MATRIX_HEADER}: {exc.args[0]}"
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=BlockedMatrixEntry(
                logical_matrix_name=trimmed_name,
                deploy_reason=INVALID_MATRIX_HEADER,
                detail=detail,
                products=(),
                machine_codes=(),
            ),
            auto_sync_disabled=False,
        )

    if not machine_codes:
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=BlockedMatrixEntry(
                logical_matrix_name=trimmed_name,
                deploy_reason=INVALID_MATRIX_HEADER,
                detail=f"{INVALID_MATRIX_HEADER}: no_machines",
                products=(),
                machine_codes=(),
            ),
            auto_sync_disabled=False,
        )

    multiplier_raw = _cell(rows, layout.matrix_multiplier_row, layout.matrix_multiplier_col)
    if not multiplier_raw:
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=BlockedMatrixEntry(
                logical_matrix_name=trimmed_name,
                deploy_reason=INVALID_MATRIX_MULTIPLIER,
                detail=f"{INVALID_MATRIX_MULTIPLIER}: missing",
                products=(),
                machine_codes=machine_codes,
            ),
            auto_sync_disabled=False,
        )
    try:
        matrix_multiplier = parse_sheet_decimal(multiplier_raw)
    except ValueError:
        matrix_multiplier = Decimal("-1")
    if not (matrix_multiplier_min <= matrix_multiplier <= matrix_multiplier_max):
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=BlockedMatrixEntry(
                logical_matrix_name=trimmed_name,
                deploy_reason=INVALID_MATRIX_MULTIPLIER,
                detail=f"{INVALID_MATRIX_MULTIPLIER}: out_of_bounds: {multiplier_raw}",
                products=(),
                machine_codes=machine_codes,
            ),
            auto_sync_disabled=False,
        )

    cells: list[MatrixCatalogCell] = []
    unknown_names: dict[str, BlockedProductRef] = {}
    product_block_hits: list[ProductBlock] = []
    line_numbers_seen: set[int] = set()
    max_col = _max_row_width(rows)
    col_step = layout.block_col_step
    row_step = layout.block_row_step
    if col_step < 1:
        msg = "block_col_step must be >= 1"
        raise ValueError(msg)
    if row_step < 1:
        msg = "block_row_step must be >= 1"
        raise ValueError(msg)

    k = 0
    while True:
        name_row = layout.product_name_row + k * row_step
        line_row = layout.line_number_row + k * row_step
        if line_row >= len(rows):
            break

        recognized_in_band = 0
        for col in range(layout.block_start_col, max_col, col_step):
            line_raw = _cell(rows, line_row, col)
            if not line_raw:
                continue
            try:
                line_number = int(line_raw)
            except ValueError:
                continue

            recognized_in_band += 1
            if line_number in line_numbers_seen:
                return MatrixCatalogTabParseResult(
                    enabled=None,
                    blocked=BlockedMatrixEntry(
                        logical_matrix_name=trimmed_name,
                        deploy_reason=INVALID_MATRIX_HEADER,
                        detail=f"{INVALID_MATRIX_HEADER}: duplicate_line_number: {line_number}",
                        products=(),
                        machine_codes=machine_codes,
                    ),
                    auto_sync_disabled=False,
                )
            line_numbers_seen.add(line_number)

            name_raw = _cell(rows, name_row, col)
            if not name_raw:
                cells.append(
                    MatrixCatalogCell(
                        line_number=line_number,
                        product_name="",
                        product_code=None,
                    ),
                )
                continue

            resolved = resolve_product_code(name_raw, name_to_code)
            if resolved.is_err():
                block_hit = _product_block_hit(
                    name_raw=name_raw,
                    product_code=None,
                    product_block_map=product_block_map,
                )
                if block_hit is not None:
                    product_block_hits.append(block_hit)
                    continue
                unknown_names[name_raw] = BlockedProductRef(
                    product_name=name_raw,
                    product_code=None,
                )
                continue

            block_hit = _product_block_hit(
                name_raw=name_raw,
                product_code=resolved.value,
                product_block_map=product_block_map,
            )
            if block_hit is not None:
                product_block_hits.append(block_hit)
                continue

            cells.append(
                MatrixCatalogCell(
                    line_number=line_number,
                    product_name=name_raw,
                    product_code=resolved.value,
                ),
            )

        if recognized_in_band == 0:
            break
        k += 1

    if product_block_hits:
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=_blocked_entry_from_product_hits(
                logical_matrix_name=trimmed_name,
                machine_codes=machine_codes,
                hits=tuple(product_block_hits),
            ),
            auto_sync_disabled=False,
        )

    if unknown_names:
        names = sorted(unknown_names)
        detail = (
            f"{UNKNOWN_PRODUCT_NAME}: {names[0]}"
            if len(names) == 1
            else f"{UNKNOWN_PRODUCT_NAME}: {', '.join(names)}"
        )
        return MatrixCatalogTabParseResult(
            enabled=None,
            blocked=BlockedMatrixEntry(
                logical_matrix_name=trimmed_name,
                deploy_reason=UNKNOWN_PRODUCT_NAME,
                detail=detail,
                products=tuple(unknown_names[name] for name in names),
                machine_codes=machine_codes,
            ),
            auto_sync_disabled=False,
        )

    return MatrixCatalogTabParseResult(
        enabled=EnabledLogicalMatrix(
            logical_matrix_name=trimmed_name,
            machine_codes=machine_codes,
            matrix_multiplier=matrix_multiplier,
            cells=tuple(cells),
        ),
        blocked=None,
        auto_sync_disabled=False,
    )
