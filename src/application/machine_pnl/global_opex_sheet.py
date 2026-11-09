from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.errors import GlobalOpExSheetError
from src.application.shared.sheet_cell_format import parse_sheet_date, parse_sheet_decimal
from src.application.shared.sheet_rows import sheet_header_matches_canonical

_CANONICAL_HEADER = (
    "valid_from",
    "labor_rate_global",
    "acquiring_percent",
    "acquiring_fee_per_sale",
    "terminal_monthly",
)


@beartype
@dataclass(frozen=True, slots=True)
class GlobalOpExSheetRow:
    valid_from: date
    labor_rate_global: Decimal | None
    acquiring_percent: Decimal | None
    acquiring_fee_per_sale: Decimal | None
    terminal_monthly: Decimal | None


@beartype
def parse_global_opex_sheet_rows(rows: list[list[str]]) -> tuple[GlobalOpExSheetRow, ...]:
    if not rows:
        raise GlobalOpExSheetError("global opex sheet is empty")
    header = tuple(cell.strip() for cell in rows[0])
    if not sheet_header_matches_canonical(header, _CANONICAL_HEADER):
        raise GlobalOpExSheetError(f"global opex header must be {_CANONICAL_HEADER}, got {header}")
    parsed: list[GlobalOpExSheetRow] = []
    for row in rows[1:]:
        if _is_empty_row(row):
            continue
        parsed.append(_parse_global_opex_data_row(row))
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
def _parse_optional_decimal(raw: str, *, field: str) -> Decimal | None:
    if not raw:
        return None
    try:
        return parse_sheet_decimal(raw)
    except ValueError as exc:
        raise GlobalOpExSheetError(f"invalid {field}: {raw!r}") from exc


@beartype
def _parse_global_opex_data_row(row: list[str]) -> GlobalOpExSheetRow:
    valid_from_raw = _cell(row, 0)
    labor_raw = _cell(row, 1)
    acquiring_percent_raw = _cell(row, 2)
    acquiring_fee_raw = _cell(row, 3)
    terminal_raw = _cell(row, 4)

    if not valid_from_raw:
        raise GlobalOpExSheetError("valid_from missing on non-empty global opex row")

    try:
        valid_from = parse_sheet_date(valid_from_raw)
    except ValueError as exc:
        raise GlobalOpExSheetError(f"invalid valid_from: {valid_from_raw!r}") from exc

    return GlobalOpExSheetRow(
        valid_from=valid_from,
        labor_rate_global=_parse_optional_decimal(labor_raw, field="labor_rate_global"),
        acquiring_percent=_parse_optional_decimal(acquiring_percent_raw, field="acquiring_percent"),
        acquiring_fee_per_sale=_parse_optional_decimal(
            acquiring_fee_raw, field="acquiring_fee_per_sale"
        ),
        terminal_monthly=_parse_optional_decimal(terminal_raw, field="terminal_monthly"),
    )
