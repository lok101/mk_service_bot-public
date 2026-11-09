from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from beartype import beartype

from src.application.shared.sheet_cell_format import parse_sheet_date, parse_sheet_decimal
from src.application.shared.sheet_rows import (
    cell_value,
    row_has_values,
)
from src.domain.ids import MachineId

LOCATION_ID_INDEX = 0
MACHINE_ID_INDEX = 3
CREATED_HEADER = "создание"
REMOVED_HEADER = "снятие"
NAME_HEADER = "полное имя"
TITLE_HEADER = "название"
LATITUDE_HEADER = "широта"
LONGITUDE_HEADER = "долгота"


@beartype
@dataclass(frozen=True, slots=True)
class LocationPlacement:
    location_id: str
    machine_id: MachineId
    installed_on: date
    removed_on: date | None
    name: str
    latitude: Decimal | None
    longitude: Decimal | None


@beartype
@dataclass(frozen=True, slots=True)
class LocationsDirectorySnapshot:
    placements: tuple[LocationPlacement, ...]
    by_location_id: dict[str, LocationPlacement]


@beartype
def build_locations_directory_snapshot(
    rows: list[list[str]],
) -> LocationsDirectorySnapshot:
    return parse_locations_directory_rows(rows)


@beartype
@dataclass(frozen=True, slots=True)
class _ColumnIndexes:
    created: int
    removed: int
    name_full: int | None
    name_title: int | None
    latitude: int
    longitude: int


@beartype
def parse_locations_directory_rows(
    rows: list[list[str]],
) -> LocationsDirectorySnapshot:
    if not rows:
        raise ValueError("Locations directory sheet is empty")
    indexes = _find_column_indexes(rows[0])
    placements: list[LocationPlacement] = []
    seen: dict[str, int] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if not row_has_values(row):
            continue
        location_id = cell_value(row, LOCATION_ID_INDEX)
        machine_code = cell_value(row, MACHINE_ID_INDEX)
        if not location_id or not machine_code:
            continue
        if location_id in seen:
            raise ValueError(
                f"Duplicate location id in directory at row {row_number}: {location_id!r}",
            )
        installed_raw = cell_value(row, indexes.created)
        try:
            installed_on = parse_sheet_date(installed_raw)
        except ValueError as error:
            raise ValueError(
                f"invalid installed_on at row {row_number}: {installed_raw!r}",
            ) from error
        removed_raw = cell_value(row, indexes.removed)
        removed_on: date | None
        if not removed_raw:
            removed_on = None
        else:
            try:
                removed_on = parse_sheet_date(removed_raw)
            except ValueError as error:
                raise ValueError(
                    f"invalid removed_on at row {row_number}: {removed_raw!r}",
                ) from error
        placement = LocationPlacement(
            location_id=location_id,
            machine_id=MachineId(machine_code),
            installed_on=installed_on,
            removed_on=removed_on,
            name=_placement_name(row, indexes),
            latitude=_parse_optional_coordinate(
                cell_value(row, indexes.latitude),
                field="latitude",
                row_number=row_number,
            ),
            longitude=_parse_optional_coordinate(
                cell_value(row, indexes.longitude),
                field="longitude",
                row_number=row_number,
            ),
        )
        seen[location_id] = row_number
        placements.append(placement)
    if not placements:
        raise ValueError("Locations directory sheet has no placement rows")
    return LocationsDirectorySnapshot(
        placements=tuple(placements),
        by_location_id={item.location_id: item for item in placements},
    )


@beartype
def _parse_optional_coordinate(
    raw: str,
    *,
    field: str,
    row_number: int,
) -> Decimal | None:
    if not raw:
        return None
    try:
        return parse_sheet_decimal(raw)
    except ValueError as error:
        raise ValueError(
            f"invalid {field} at row {row_number}: {raw!r}",
        ) from error


@beartype
def _normalize_directory_header(cell: str) -> str:
    return " ".join(cell.replace("\xa0", " ").split()).casefold()


@beartype
def _optional_header_index(normalized: list[str], header: str) -> int | None:
    try:
        return normalized.index(header)
    except ValueError:
        return None


@beartype
def _placement_name(row: list[str], indexes: _ColumnIndexes) -> str:
    if indexes.name_full is not None:
        full_name = cell_value(row, indexes.name_full)
        if full_name:
            return full_name
    if indexes.name_title is not None:
        return cell_value(row, indexes.name_title)
    return ""


@beartype
def _find_column_indexes(header_row: list[str]) -> _ColumnIndexes:
    normalized = [_normalize_directory_header(cell) for cell in header_row]
    try:
        created = normalized.index(CREATED_HEADER)
        removed = normalized.index(REMOVED_HEADER)
        latitude = normalized.index(LATITUDE_HEADER)
        longitude = normalized.index(LONGITUDE_HEADER)
    except ValueError as error:
        raise ValueError(
            "Locations directory sheet must contain Создание, Снятие, Широта and Долгота columns",
        ) from error
    name_full = _optional_header_index(normalized, NAME_HEADER)
    name_title = _optional_header_index(normalized, TITLE_HEADER)
    if name_full is None and name_title is None:
        raise ValueError(
            "Locations directory sheet must contain Полное имя or Название column",
        )
    return _ColumnIndexes(
        created=created,
        removed=removed,
        name_full=name_full,
        name_title=name_title,
        latitude=latitude,
        longitude=longitude,
    )
