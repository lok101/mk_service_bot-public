from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.application.reference_data import ReferenceDataProvider
from src.application.sheets import (
    find_technician_id_for_machine_in_snapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine


@beartype
@dataclass(slots=True)
class GoogleSheetsVendingMachineRepository(VendingMachineRepository):
    provider: ReferenceDataProvider

    @beartype
    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        snapshot = self.provider.service_locations_or_none()
        if snapshot is None:
            return []
        return list(snapshot.machines_by_technician_id.get(technician_id, ()))

    @beartype
    def list_all(self) -> list[VendingMachine]:
        snapshot = self.provider.service_locations_or_none()
        if snapshot is None:
            return []
        return list_all_machines_from_snapshot(snapshot)

    @beartype
    def find_technician_id_for_machine(
        self,
        machine_id: MachineId,
    ) -> TechnicianId | None:
        snapshot = self.provider.service_locations_or_none()
        if snapshot is None:
            return None
        return find_technician_id_for_machine_in_snapshot(snapshot, machine_id)

    @beartype
    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        technician_id = self.find_technician_id_for_machine(machine_id)
        if technician_id is None:
            return None
        return self.find_technician_display_name(technician_id)

    @beartype
    def find_technician_display_name(
        self,
        technician_id: TechnicianId,
    ) -> str | None:
        directory = self.provider.technicians_directory_or_none()
        if directory is None:
            return None
        name = directory.names_by_id.get(technician_id)
        if name is None:
            return None
        stripped = name.strip()
        return stripped or None

    @beartype
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        snapshot = self.provider.service_locations_or_none()
        if snapshot is None:
            return None
        for machine in list_all_machines_from_snapshot(snapshot):
            if machine.id == machine_id:
                return machine
        return None
