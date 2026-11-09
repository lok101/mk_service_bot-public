from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.shared.sheet_rows import (
    cell_value,
    normalize_header_cells,
    row_has_values,
)
from src.domain.ids import TechnicianId

TECHNICIAN_ID_COLUMN = "id"
TECHNICIAN_NAME_COLUMN = "имя"


@beartype
@dataclass(frozen=True, slots=True)
class TechniciansDirectorySnapshot:
    names_by_id: dict[TechnicianId, str]


@beartype
def build_technicians_directory_snapshot(
    rows: list[list[str]],
) -> TechniciansDirectorySnapshot:
    return parse_technicians_directory_rows(rows)


@beartype
def parse_technicians_directory_rows(
    rows: list[list[str]],
) -> TechniciansDirectorySnapshot:
    if not rows:
        raise ValueError("Technicians directory sheet is empty")
    indexes = _find_column_indexes(rows[0])
    names_by_id: dict[TechnicianId, str] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if not row_has_values(row):
            continue
        tech_code = cell_value(row, indexes.technician_id)
        tech_name = cell_value(row, indexes.technician_name)
        if not tech_code or not tech_name:
            continue
        technician_id = TechnicianId(tech_code)
        if technician_id in names_by_id:
            raise ValueError(
                f"Duplicate technician id in directory at row {row_number}: {tech_code!r}",
            )
        names_by_id[technician_id] = tech_name
    if not names_by_id:
        raise ValueError("Technicians directory sheet has no id/name rows")
    return TechniciansDirectorySnapshot(names_by_id=names_by_id)


@beartype
@dataclass(frozen=True, slots=True)
class _ColumnIndexes:
    technician_id: int
    technician_name: int


@beartype
def _find_column_indexes(header_row: list[str]) -> _ColumnIndexes:
    normalized = normalize_header_cells(header_row)
    try:
        return _ColumnIndexes(
            technician_id=normalized.index(TECHNICIAN_ID_COLUMN),
            technician_name=normalized.index(TECHNICIAN_NAME_COLUMN),
        )
    except ValueError as error:
        raise ValueError(
            "Technicians directory sheet must contain Id and Имя columns",
        ) from error
