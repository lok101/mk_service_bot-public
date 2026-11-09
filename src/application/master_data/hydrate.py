from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
)
from src.application.master_data.ports import MasterDataStores
from src.application.sheets import (
    LocationPlacement,
    LocationsDirectorySnapshot,
    TechnicianLocationsSnapshot,
)
from src.domain.models import VendingMachine


@runtime_checkable
class MasterDataSnapshotSink(Protocol):
    def apply_master_snapshots(
        self,
        *,
        coffee: TechnicianLocationsSnapshot | None,
        snack: TechnicianLocationsSnapshot | None,
        micromarket: TechnicianLocationsSnapshot | None = None,
        locations_directory: LocationsDirectorySnapshot | None,
    ) -> None: ...


@beartype
def hydrate_provider_from_master_data(
    sink: MasterDataSnapshotSink,
    stores: MasterDataStores,
) -> None:
    coffee_machines: list[VendingMachine] = []
    snack_machines: list[VendingMachine] = []
    micromarket_machines: list[VendingMachine] = []
    for machine in stores.machines.list_all():
        display = _machine_display_name(machine, stores)
        vm = VendingMachine(
            id=machine.machine_id,
            name=display,
            service_weekdays=frozenset(),
        )
        if machine.kind is MachineKind.COFFEE:
            coffee_machines.append(vm)
        elif machine.kind is MachineKind.SNACK:
            snack_machines.append(vm)
        elif machine.kind is MachineKind.MICRO_MARKET:
            micromarket_machines.append(vm)

    coffee = TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=tuple(coffee_machines),
    )
    snack = TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=tuple(snack_machines),
    )
    micromarket = TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=tuple(micromarket_machines),
    )
    directory = _build_locations_directory(stores)
    sink.apply_master_snapshots(
        coffee=coffee,
        snack=snack,
        micromarket=micromarket,
        locations_directory=directory,
    )


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
    return location.display_name


@beartype
def _build_locations_directory(
    stores: MasterDataStores,
) -> LocationsDirectorySnapshot:
    placements = sorted(
        stores.placements.list_all(),
        key=lambda placement: (placement.valid_from, placement.placement_id),
    )
    if not placements:
        return LocationsDirectorySnapshot(placements=(), by_location_id={})

    locations_by_id = {loc.location_id: loc for loc in stores.locations.list_all()}
    built: list[LocationPlacement] = []
    for placement in placements:
        location = locations_by_id.get(placement.location_id)
        built.append(_to_location_placement(placement, location))

    return LocationsDirectorySnapshot(
        placements=tuple(built),
        by_location_id={item.location_id: item for item in built},
    )


@beartype
def _to_location_placement(
    placement: MasterPlacement,
    location: MasterLocation | None,
) -> LocationPlacement:
    name = "" if location is None else location.display_name
    latitude = None if location is None else location.latitude
    longitude = None if location is None else location.longitude
    return LocationPlacement(
        location_id=placement.location_id,
        machine_id=placement.machine_id,
        installed_on=placement.valid_from.date(),
        removed_on=None if placement.valid_to is None else placement.valid_to.date(),
        name=name,
        latitude=latitude,
        longitude=longitude,
    )
