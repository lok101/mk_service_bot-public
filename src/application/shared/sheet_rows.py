from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype


@beartype
def sheet_header_matches_canonical(header: Sequence[str], canonical: Sequence[str]) -> bool:
    """True when header starts with canonical columns; trailing grid extras ignored."""
    if len(header) < len(canonical):
        return False
    return tuple(header[: len(canonical)]) == tuple(canonical)


@beartype
def cell_value(row: list[str], column_index: int) -> str:
    if column_index >= len(row):
        return ""

    return row[column_index].strip()


@beartype
def row_has_values(row: list[str]) -> bool:
    return any(cell.strip() for cell in row)


@beartype
def is_active_cell(value: str) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return False

    return normalized in {"true", "1", "yes", "да"}


@beartype
def normalize_header_cells(header_row: list[str]) -> list[str]:
    return [cell.strip().casefold() for cell in header_row]
