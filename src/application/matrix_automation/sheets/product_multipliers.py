from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.errors import ProductMultipliersParseError
from src.application.matrix_automation.models import ProductBlock
from src.application.shared.sheet_cell_format import parse_sheet_decimal


@beartype
@dataclass(frozen=True, slots=True)
class ProductMultipliersParseResult:
    multipliers: dict[str, Decimal]
    product_block_map: dict[str, ProductBlock]


@beartype
def _cell(rows: list[list[str]], row: int, col: int) -> str:
    if row >= len(rows):
        return ""
    line = rows[row]
    if col >= len(line):
        return ""
    return line[col].strip()


@beartype
def _find_header_row(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows):
        a = _cell([row], 0, 0).lower()
        c = _cell([row], 0, 2).lower()
        if a == "product_code" and c.startswith("multiplier"):
            return index
    return None


@beartype
def parse_product_multipliers_sheet(
    rows: list[list[str]],
    *,
    min_bound: Decimal,
    max_bound: Decimal,
) -> ProductMultipliersParseResult:
    header_row = _find_header_row(rows)
    if header_row is None:
        raise ProductMultipliersParseError("missing product_multipliers header row")

    multipliers: dict[str, Decimal] = {}
    product_block_map: dict[str, ProductBlock] = {}
    code_counts: dict[str, int] = {}

    for row in rows[header_row + 1 :]:
        code = _cell([row], 0, 0)
        multiplier_raw = _cell([row], 0, 2)
        if not code and not multiplier_raw:
            continue
        if not code and multiplier_raw:
            product_block_map[f"row:{id(row)}"] = ProductBlock(
                product_name=None,
                product_code=None,
                detail="invalid_product_row: empty code with multiplier",
            )
            continue
        code_counts[code] = code_counts.get(code, 0) + 1
        if not multiplier_raw:
            multipliers[code] = Decimal("1")
            continue
        try:
            value = parse_sheet_decimal(multiplier_raw)
        except ValueError:
            product_block_map[code] = ProductBlock(
                product_name=_cell([row], 0, 1) or None,
                product_code=code,
                detail=f"invalid_product_row: {code}",
            )
            continue
        if not (min_bound <= value <= max_bound):
            product_block_map[code] = ProductBlock(
                product_name=_cell([row], 0, 1) or None,
                product_code=code,
                detail=f"product_multiplier_out_of_bounds: {code}",
            )
            continue
        multipliers[code] = value

    for code, count in code_counts.items():
        if count > 1:
            product_block_map[code] = ProductBlock(
                product_name=None,
                product_code=code,
                detail=f"duplicate_product_multiplier: {code}",
            )

    clean_multipliers = {
        code: value for code, value in multipliers.items() if code not in product_block_map
    }
    return ProductMultipliersParseResult(
        multipliers=clean_multipliers,
        product_block_map=product_block_map,
    )
