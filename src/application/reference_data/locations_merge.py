from __future__ import annotations

from beartype import beartype

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.sheets import (
    TechnicianLocationsSnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import TechnicianId
from src.domain.machine_sales_classify import is_snack_machine_code
from src.domain.models import VendingMachine


@beartype
def assert_locations_kind_for_source(
    snapshot: TechnicianLocationsSnapshot,
    source_id: ReferenceDataSourceId,
) -> None:
    machines = list_all_machines_from_snapshot(snapshot)
    if source_id is ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS:
        for machine in machines:
            if is_snack_machine_code(machine.id.value):
                msg = f"Snack machine id not allowed on coffee sheet: {machine.id.value!r}"
                raise ValueError(msg)
        return
    if source_id is ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS:
        for machine in machines:
            if not is_snack_machine_code(machine.id.value):
                msg = f"Non-snack machine id not allowed on snack sheet: {machine.id.value!r}"
                raise ValueError(msg)
        return
    msg = f"unsupported locations source for kind gate: {source_id}"
    raise ValueError(msg)


@beartype
def assert_locations_merge_compatible(
    incoming: TechnicianLocationsSnapshot,
    other: TechnicianLocationsSnapshot,
) -> None:
    incoming_ids = {m.id.value for m in list_all_machines_from_snapshot(incoming)}
    other_ids = {m.id.value for m in list_all_machines_from_snapshot(other)}
    collision = incoming_ids & other_ids
    if collision:
        sample = sorted(collision)[0]
        msg = f"Duplicate machine_id collision across location sheets: {sample!r}"
        raise ValueError(msg)

    for technician_id, incoming_name in incoming.technician_names_by_id.items():
        other_name = other.technician_names_by_id.get(technician_id)
        if other_name is None:
            continue
        if incoming_name.strip() != other_name.strip():
            msg = (
                f"Technician name conflict for {technician_id.value!r}: "
                f"{other_name!r} vs {incoming_name!r}"
            )
            raise ValueError(msg)


@beartype
def _merge_two_location_snapshots(
    left: TechnicianLocationsSnapshot,
    right: TechnicianLocationsSnapshot,
) -> TechnicianLocationsSnapshot:
    machines_by_technician_id: dict[TechnicianId, list[VendingMachine]] = {
        technician_id: list(machines)
        for technician_id, machines in left.machines_by_technician_id.items()
    }
    technician_names_by_id = dict(left.technician_names_by_id)
    unassigned_machines = list(left.unassigned_machines)

    for technician_id, machines in right.machines_by_technician_id.items():
        machines_by_technician_id.setdefault(technician_id, []).extend(machines)
    for technician_id, name in right.technician_names_by_id.items():
        technician_names_by_id.setdefault(technician_id, name)
    unassigned_machines.extend(right.unassigned_machines)

    return TechnicianLocationsSnapshot(
        machines_by_technician_id={
            technician_id: tuple(machines)
            for technician_id, machines in machines_by_technician_id.items()
        },
        technician_names_by_id=technician_names_by_id,
        unassigned_machines=tuple(unassigned_machines),
    )


@beartype
def merge_locations_catalog(
    coffee: TechnicianLocationsSnapshot | None,
    snack: TechnicianLocationsSnapshot | None,
    micromarket: TechnicianLocationsSnapshot | None = None,
) -> TechnicianLocationsSnapshot | None:
    present = [snap for snap in (coffee, snack, micromarket) if snap is not None]
    if not present:
        return None
    if len(present) == 1:
        return present[0]

    result = present[0]
    for other in present[1:]:
        assert_locations_merge_compatible(other, result)
        result = _merge_two_location_snapshots(result, other)
    return result


@beartype
def filter_locations_by_machine_ids(
    catalog: TechnicianLocationsSnapshot,
    allowed_ids: frozenset[str],
) -> TechnicianLocationsSnapshot:
    machines_by_technician_id: dict[TechnicianId, tuple[VendingMachine, ...]] = {}
    for technician_id, machines in catalog.machines_by_technician_id.items():
        kept = tuple(machine for machine in machines if machine.id.value in allowed_ids)
        if kept:
            machines_by_technician_id[technician_id] = kept
    technician_names_by_id = {
        technician_id: name
        for technician_id, name in catalog.technician_names_by_id.items()
        if technician_id in machines_by_technician_id
    }
    unassigned_machines = tuple(
        machine for machine in catalog.unassigned_machines if machine.id.value in allowed_ids
    )
    return TechnicianLocationsSnapshot(
        machines_by_technician_id=machines_by_technician_id,
        technician_names_by_id=technician_names_by_id,
        unassigned_machines=unassigned_machines,
    )


@beartype
def filter_coffee_locations(
    catalog: TechnicianLocationsSnapshot,
) -> TechnicianLocationsSnapshot:
    machines_by_technician_id: dict[TechnicianId, tuple[VendingMachine, ...]] = {}
    for technician_id, machines in catalog.machines_by_technician_id.items():
        coffee_machines = tuple(
            machine for machine in machines if not is_snack_machine_code(machine.id.value)
        )
        if coffee_machines:
            machines_by_technician_id[technician_id] = coffee_machines

    technician_names_by_id = {
        technician_id: name
        for technician_id, name in catalog.technician_names_by_id.items()
        if technician_id in machines_by_technician_id
    }
    unassigned_machines = tuple(
        machine
        for machine in catalog.unassigned_machines
        if not is_snack_machine_code(machine.id.value)
    )
    return TechnicianLocationsSnapshot(
        machines_by_technician_id=machines_by_technician_id,
        technician_names_by_id=technician_names_by_id,
        unassigned_machines=unassigned_machines,
    )
