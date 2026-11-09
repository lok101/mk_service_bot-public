from __future__ import annotations

from beartype import beartype

from src.application.reference_data.ports import LocationRosterStore
from src.application.sheets import (
    TechnicianLocationsSnapshot,
    TechniciansDirectorySnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import TechnicianId
from src.domain.models import VendingMachine


@beartype
def overlay_location_roster(
    fleet: TechnicianLocationsSnapshot,
    *,
    store: LocationRosterStore,
    directory: TechniciansDirectorySnapshot | None,
) -> TechnicianLocationsSnapshot:
    machines_by_technician_id: dict[TechnicianId, list[VendingMachine]] = {}
    unassigned_machines: list[VendingMachine] = []
    assigned_technician_ids: set[TechnicianId] = set()

    for machine in list_all_machines_from_snapshot(fleet):
        entry = store.get(machine.id)
        technician_id = None if entry is None else entry.technician_id
        service_weekdays = frozenset() if entry is None else entry.service_weekdays
        overlaid = VendingMachine(
            id=machine.id,
            name=machine.name,
            service_weekdays=service_weekdays,
        )
        if technician_id is None:
            unassigned_machines.append(overlaid)
            continue
        assigned_technician_ids.add(technician_id)
        machines_by_technician_id.setdefault(technician_id, []).append(overlaid)

    technician_names_by_id: dict[TechnicianId, str] = {}
    if directory is not None:
        for technician_id in assigned_technician_ids:
            name = directory.names_by_id.get(technician_id)
            if name is not None:
                technician_names_by_id[technician_id] = name

    return TechnicianLocationsSnapshot(
        machines_by_technician_id={
            technician_id: tuple(machines)
            for technician_id, machines in machines_by_technician_id.items()
        },
        technician_names_by_id=technician_names_by_id,
        unassigned_machines=tuple(unassigned_machines),
    )
