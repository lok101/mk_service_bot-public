from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from beartype import beartype

from src.application.master_data import (
    MachineStatus,
    MasterDataStores,
    MasterMachine,
    effective_location_display_name,
    location_address_parts_complete,
)
from src.domain.ids import MachineId


@beartype
def machine_profile_display_name(stores: MasterDataStores, machine: MasterMachine) -> str:
    open_placement = stores.placements.get_open(machine.machine_id)
    if open_placement is not None:
        location = stores.locations.get(open_placement.location_id)
        if location is not None:
            return effective_location_display_name(
                name=location.name,
                city=location.city,
                street=location.street,
                house=location.house,
                display_name=location.display_name,
            )
        return machine.machine_id.value
    label = (machine.label or "").strip()
    if label:
        return f"[склад] {label}"
    return f"[склад] {machine.machine_id.value}"


@beartype
@dataclass(frozen=True, slots=True)
class MasterMachineRowView:
    machine_id: str
    kind: str
    status: str
    location_id: str | None
    location_name: str | None
    city: str | None
    company_name: str


@beartype
@dataclass(frozen=True, slots=True)
class MasterMachinesViewModel:
    rows: tuple[MasterMachineRowView, ...]


@beartype
@dataclass(frozen=True, slots=True)
class MasterLocationFormView:
    location_id: str
    name: str
    city: str
    street: str
    house: str
    legacy_display_name: str
    show_legacy_hint: bool
    latitude: str
    longitude: str


@beartype
def build_master_machines_view(
    stores: MasterDataStores,
    *,
    company_names: Mapping[MachineId, str],
) -> MasterMachinesViewModel:
    rows: list[MasterMachineRowView] = []
    for machine in sorted(stores.machines.list_all(), key=lambda m: m.machine_id.value):
        open_placement = stores.placements.get_open(machine.machine_id)
        location_id: str | None = None
        location_name: str | None = None
        city: str | None = None
        if open_placement is not None:
            location_id = open_placement.location_id
            location = stores.locations.get(open_placement.location_id)
            if location is not None:
                location_name = effective_location_display_name(
                    name=location.name,
                    city=location.city,
                    street=location.street,
                    house=location.house,
                    display_name=location.display_name,
                )
                city = location.city or None
        elif machine.status is MachineStatus.IN_STORAGE:
            location_name = "Склад"
        company_name = str(company_names.get(machine.machine_id, "") or "")
        rows.append(
            MasterMachineRowView(
                machine_id=machine.machine_id.value,
                kind=machine.kind.value,
                status=machine.status.value,
                location_id=location_id,
                location_name=location_name,
                city=city,
                company_name=company_name,
            )
        )
    return MasterMachinesViewModel(rows=tuple(rows))


@beartype
def build_location_form_view(
    stores: MasterDataStores,
    location_id: str,
) -> MasterLocationFormView | None:
    location = stores.locations.get(location_id)
    if location is None:
        return None
    incomplete = not location_address_parts_complete(
        name=location.name,
        city=location.city,
        street=location.street,
        house=location.house,
    )
    return MasterLocationFormView(
        location_id=location.location_id,
        name=location.name,
        city=location.city,
        street=location.street,
        house=location.house,
        legacy_display_name=location.display_name,
        show_legacy_hint=incomplete,
        latitude="" if location.latitude is None else str(location.latitude),
        longitude="" if location.longitude is None else str(location.longitude),
    )
