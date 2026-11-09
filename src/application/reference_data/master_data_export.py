from __future__ import annotations

from beartype import beartype

from src.application.master_data import (
    MachineStatus,
    MasterDataStores,
    MasterMachine,
    TechnicianStore,
    effective_location_display_name,
)
from src.application.reference_data.ports import LocationRosterStore
from src.application.shared.sheet_cell_format import (
    format_sheet_date,
    format_sheet_decimal,
)
from src.domain.ids import MachineId, TechnicianId

MACHINES_MIRROR_EXPORT_HEADER: list[str] = [
    "Id",
    "Имя локации",
    "Имя техника",
    "Id техника",
    "Kind",
    "Компания",
]

LOCATIONS_DIRECTORY_EXPORT_HEADER: list[str] = [
    "Id",
    "Создание",
    "Снятие",
    "Id торговой точки",
    "Название",
    "Полное имя",
    "Город",
    "Улица",
    "Дом",
    "Широта",
    "Долгота",
]

TECHNICIANS_EXPORT_HEADER: list[str] = [
    "Id",
    "Имя",
]


@beartype
def _location_id_mirror_sort_key(location_id: str) -> tuple[int, int | str]:
    try:
        return (0, -int(location_id))
    except ValueError:
        return (1, location_id)


@beartype
def build_machines_mirror_export_rows(
    stores: MasterDataStores,
    *,
    roster: LocationRosterStore,
    technician_names: dict[TechnicianId, str],
    company_names: dict[MachineId, str],
) -> list[list[str]]:
    rows: list[list[str]] = [list(MACHINES_MIRROR_EXPORT_HEADER)]
    machines = sorted(stores.machines.list_all(), key=lambda m: m.machine_id.value)
    for machine in machines:
        entry = roster.get(machine.machine_id)
        tech_id = ""
        tech_name = ""
        if entry is not None and entry.technician_id is not None:
            tech_id = entry.technician_id.value
            tech_name = technician_names.get(entry.technician_id, "")
        kind = machine.kind.value
        company = company_names.get(machine.machine_id, "")
        rows.append(
            [
                machine.machine_id.value,
                _machine_display_name(machine, stores),
                tech_name,
                tech_id,
                kind,
                company,
            ]
        )
    return rows


@beartype
def build_locations_directory_export_rows(
    stores: MasterDataStores,
) -> list[list[str]]:
    rows: list[list[str]] = [list(LOCATIONS_DIRECTORY_EXPORT_HEADER)]
    locations_by_id = {loc.location_id: loc for loc in stores.locations.list_all()}
    placements = sorted(
        stores.placements.list_all(),
        key=lambda p: (
            _location_id_mirror_sort_key(p.location_id),
            -p.valid_from.timestamp(),
            p.placement_id,
        ),
    )
    for placement in placements:
        location = locations_by_id.get(placement.location_id)
        name = "" if location is None else location.name
        city = "" if location is None else location.city
        street = "" if location is None else location.street
        house = "" if location is None else location.house
        full_name = ""
        if location is not None:
            full_name = effective_location_display_name(
                name=location.name,
                city=location.city,
                street=location.street,
                house=location.house,
                display_name=location.display_name,
            )
        lat = ""
        lon = ""
        if location is not None and location.latitude is not None:
            lat = format_sheet_decimal(location.latitude)
        if location is not None and location.longitude is not None:
            lon = format_sheet_decimal(location.longitude)
        removed = ""
        if placement.valid_to is not None:
            removed = format_sheet_date(placement.valid_to.date())
        rows.append(
            [
                placement.location_id,
                format_sheet_date(placement.valid_from.date()),
                removed,
                placement.machine_id.value,
                name,
                full_name,
                city,
                street,
                house,
                lat,
                lon,
            ]
        )
    return rows


@beartype
def build_technicians_directory_export_rows(
    store: TechnicianStore,
) -> list[list[str]]:
    rows: list[list[str]] = [list(TECHNICIANS_EXPORT_HEADER)]
    technicians = sorted(store.list_all(), key=lambda t: t.technician_id.value)
    for technician in technicians:
        rows.append([technician.technician_id.value, technician.name])
    return rows


@beartype
def _machine_display_name(machine: MasterMachine, stores: MasterDataStores) -> str:
    if machine.status is MachineStatus.IN_STORAGE:
        label = (machine.label or "").strip()
        if label:
            return f"[склад] {label}"
        return f"[склад] {machine.machine_id.value}"

    open_placement = stores.placements.get_open(machine.machine_id)
    if open_placement is None:
        label = (machine.label or "").strip()
        if label:
            return f"[склад] {label}"
        return f"[склад] {machine.machine_id.value}"

    location = stores.locations.get(open_placement.location_id)
    if location is None:
        return machine.machine_id.value
    return effective_location_display_name(
        name=location.name,
        city=location.city,
        street=location.street,
        house=location.house,
        display_name=location.display_name,
    )
