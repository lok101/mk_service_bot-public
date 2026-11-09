from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from beartype import beartype

from src.application.shared.sheet_rows import (
    cell_value,
    is_active_cell,
    normalize_header_cells,
    row_has_values,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine

LOCATION_ID_COLUMN = "id локации"
LOCATION_NAME_COLUMN = "имя локации"
TECHNICIAN_NAME_COLUMN = "имя техника"
TECHNICIAN_ID_COLUMN = "id техника"
_WEEKDAY_HEADERS: tuple[str, ...] = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianLocationsSnapshot:
    machines_by_technician_id: dict[TechnicianId, tuple[VendingMachine, ...]]
    technician_names_by_id: dict[TechnicianId, str]
    unassigned_machines: tuple[VendingMachine, ...] = field(default_factory=tuple)


@beartype
def build_technician_locations_snapshot(
    rows: list[list[str]],
    *,
    assignments: Literal["sheet", "fleet"] = "sheet",
) -> TechnicianLocationsSnapshot:
    return parse_technician_location_rows(rows, assignments=assignments)


@beartype
def list_all_machines_from_snapshot(
    snapshot: TechnicianLocationsSnapshot,
) -> list[VendingMachine]:
    machines_by_id: dict[MachineId, VendingMachine] = {}
    for machines in snapshot.machines_by_technician_id.values():
        for machine in machines:
            machines_by_id[machine.id] = machine
    for machine in snapshot.unassigned_machines:
        machines_by_id.setdefault(machine.id, machine)

    return list(machines_by_id.values())


@beartype
def find_technician_display_name_in_snapshot(
    snapshot: TechnicianLocationsSnapshot,
    technician_id: TechnicianId,
) -> str | None:
    return snapshot.technician_names_by_id.get(technician_id)


@beartype
def find_technician_id_for_machine_in_snapshot(
    snapshot: TechnicianLocationsSnapshot,
    machine_id: MachineId,
) -> TechnicianId | None:
    for technician_id, machines in snapshot.machines_by_technician_id.items():
        if any(machine.id == machine_id for machine in machines):
            return technician_id

    return None


@beartype
def find_technician_display_name_for_machine_in_snapshot(
    snapshot: TechnicianLocationsSnapshot,
    machine_id: MachineId,
) -> str | None:
    technician_id = find_technician_id_for_machine_in_snapshot(snapshot, machine_id)
    if technician_id is None:
        return None

    return snapshot.technician_names_by_id.get(technician_id)


@beartype
def parse_technician_location_rows(
    rows: list[list[str]],
    *,
    assignments: Literal["sheet", "fleet"] = "sheet",
) -> TechnicianLocationsSnapshot:
    if not rows:
        raise ValueError("Technician locations sheet is empty")

    if assignments == "fleet":
        return _parse_fleet_location_rows(rows)

    column_indexes = _find_technician_location_column_indexes(rows[0])
    machines_by_technician_id: dict[TechnicianId, list[VendingMachine]] = {}
    technician_names_by_id: dict[TechnicianId, str] = {}
    unassigned_machines: list[VendingMachine] = []
    location_ids: set[str] = set()

    for row_number, row in enumerate(rows[1:], start=2):
        if not row_has_values(row):
            continue

        location_id = cell_value(row, column_indexes.location_id)
        location_name = cell_value(row, column_indexes.location_name)
        technician_name = cell_value(row, column_indexes.technician_name)
        technician_code = cell_value(row, column_indexes.technician_id)

        if not location_id or not location_name:
            continue

        if location_id in location_ids:
            raise ValueError(
                f"Duplicate location id in sheet at row {row_number}: {location_id!r}",
            )

        location_ids.add(location_id)

        if technician_name and not technician_code:
            raise ValueError(
                f"Technician id is missing for technician {technician_name!r} at row {row_number}",
            )

        weekdays: set[int] = set()
        for iso_weekday, column_index in enumerate(column_indexes.weekdays):
            if column_index is None:
                continue
            if is_active_cell(cell_value(row, column_index)):
                weekdays.add(iso_weekday)
        machine = VendingMachine(
            id=MachineId(location_id),
            name=location_name,
            service_weekdays=frozenset(weekdays),
        )

        if not technician_code:
            unassigned_machines.append(machine)
            continue

        technician_id = TechnicianId(technician_code)

        existing_name = technician_names_by_id.get(technician_id)
        if existing_name is not None and technician_name and existing_name != technician_name:
            raise ValueError(
                f"Conflicting technician names for id {technician_code!r} "
                f"at row {row_number}: {existing_name!r} vs {technician_name!r}",
            )

        if technician_name:
            technician_names_by_id[technician_id] = technician_name

        machines_by_technician_id.setdefault(technician_id, []).append(machine)

    if not location_ids:
        raise ValueError("Technician locations sheet has no location rows")

    return TechnicianLocationsSnapshot(
        machines_by_technician_id={
            technician_id: tuple(machines)
            for technician_id, machines in machines_by_technician_id.items()
        },
        technician_names_by_id=technician_names_by_id,
        unassigned_machines=tuple(unassigned_machines),
    )


@beartype
def _parse_fleet_location_rows(rows: list[list[str]]) -> TechnicianLocationsSnapshot:
    location_id_index, location_name_index = _find_fleet_location_column_indexes(rows[0])
    unassigned_machines: list[VendingMachine] = []
    location_ids: set[str] = set()

    for row_number, row in enumerate(rows[1:], start=2):
        if not row_has_values(row):
            continue

        location_id = cell_value(row, location_id_index)
        location_name = cell_value(row, location_name_index)
        if not location_id or not location_name:
            continue

        if location_id in location_ids:
            raise ValueError(
                f"Duplicate location id in sheet at row {row_number}: {location_id!r}",
            )

        location_ids.add(location_id)
        unassigned_machines.append(
            VendingMachine(
                id=MachineId(location_id),
                name=location_name,
                service_weekdays=frozenset(),
            ),
        )

    if not location_ids:
        raise ValueError("Technician locations sheet has no location rows")

    return TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=tuple(unassigned_machines),
    )


@beartype
def _find_fleet_location_column_indexes(header_row: list[str]) -> tuple[int, int]:
    normalized_headers = normalize_header_cells(header_row)
    try:
        return (
            normalized_headers.index(LOCATION_ID_COLUMN),
            normalized_headers.index(LOCATION_NAME_COLUMN),
        )
    except ValueError as error:
        raise ValueError(
            "Technician locations sheet must contain Id локации and Имя локации columns",
        ) from error


@beartype
@dataclass(frozen=True, slots=True)
class _TechnicianLocationColumnIndexes:
    location_id: int
    location_name: int
    technician_name: int
    technician_id: int
    weekdays: tuple[int | None, ...]


@beartype
def _find_technician_location_column_indexes(
    header_row: list[str],
) -> _TechnicianLocationColumnIndexes:
    normalized_headers = normalize_header_cells(header_row)

    try:
        return _TechnicianLocationColumnIndexes(
            location_id=normalized_headers.index(LOCATION_ID_COLUMN),
            location_name=normalized_headers.index(LOCATION_NAME_COLUMN),
            technician_name=normalized_headers.index(TECHNICIAN_NAME_COLUMN),
            technician_id=normalized_headers.index(TECHNICIAN_ID_COLUMN),
            weekdays=tuple(
                normalized_headers.index(header) if header in normalized_headers else None
                for header in _WEEKDAY_HEADERS
            ),
        )
    except ValueError as error:
        raise ValueError(
            "Technician locations sheet must contain "
            "Id локации, Имя локации, Имя техника, and Id техника columns",
        ) from error
