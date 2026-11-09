from __future__ import annotations

from datetime import date

from beartype import beartype

from src.application.machine_pnl.errors import UnitCostSheetError
from src.application.machine_pnl.unit_cost import UnitCostRow
from src.application.shared.sheet_cell_format import parse_sheet_date, parse_sheet_decimal
from src.application.shared.sheet_rows import sheet_header_matches_canonical

_CANONICAL_HEADER = ("product_code", "unit_cost", "valid_from", "valid_to")


@beartype
def parse_unit_cost_sheet_rows(rows: list[list[str]]) -> tuple[UnitCostRow, ...]:
    if not rows:
        raise UnitCostSheetError("unit cost sheet is empty")
    header = tuple(cell.strip() for cell in rows[0])
    if not sheet_header_matches_canonical(header, _CANONICAL_HEADER):
        raise UnitCostSheetError(
            f"unit cost sheet header must be {_CANONICAL_HEADER}, got {header}"
        )

    parsed: list[UnitCostRow] = []
    seen: set[tuple[str, date]] = set()
    for row in rows[1:]:
        if _is_empty_row(row):
            continue
        unit_cost_row = _parse_data_row(row)
        key = (unit_cost_row.product_code, unit_cost_row.valid_from)
        if key in seen:
            raise UnitCostSheetError(
                "duplicate unit cost row for "
                f"({unit_cost_row.product_code!r}, {unit_cost_row.valid_from.isoformat()})"
            )
        seen.add(key)
        parsed.append(unit_cost_row)
    return tuple(parsed)


@beartype
def _is_empty_row(row: list[str]) -> bool:
    return all(not cell.strip() for cell in row)


@beartype
def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


@beartype
def _parse_data_row(row: list[str]) -> UnitCostRow:
    product_code = _cell(row, 0)
    unit_cost_raw = _cell(row, 1)
    valid_from_raw = _cell(row, 2)
    valid_to_raw = _cell(row, 3)

    if not product_code:
        raise UnitCostSheetError("unit cost row missing product_code")
    if not unit_cost_raw:
        raise UnitCostSheetError(f"unit cost missing for product_code={product_code!r}")
    if not valid_from_raw:
        raise UnitCostSheetError(f"valid_from missing for product_code={product_code!r}")

    try:
        unit_cost = parse_sheet_decimal(unit_cost_raw)
    except ValueError as exc:
        raise UnitCostSheetError(
            f"invalid unit_cost for product_code={product_code!r}: {unit_cost_raw!r}"
        ) from exc
    if unit_cost < 0:
        raise UnitCostSheetError(f"unit_cost must be >= 0 for product_code={product_code!r}")

    try:
        valid_from = parse_sheet_date(valid_from_raw)
    except ValueError as exc:
        raise UnitCostSheetError(
            f"invalid valid_from for product_code={product_code!r}: {valid_from_raw!r}"
        ) from exc

    valid_to: date | None
    if not valid_to_raw:
        valid_to = None
    else:
        try:
            valid_to = parse_sheet_date(valid_to_raw)
        except ValueError as exc:
            raise UnitCostSheetError(
                f"invalid valid_to for product_code={product_code!r}: {valid_to_raw!r}"
            ) from exc

    return UnitCostRow(
        product_code=product_code,
        unit_cost=unit_cost,
        valid_from=valid_from,
        valid_to=valid_to,
    )
