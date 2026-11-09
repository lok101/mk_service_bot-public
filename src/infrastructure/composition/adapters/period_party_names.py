from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class VendingMachinePeriodPartyNamesLookup:
    machines: VendingMachineRepository

    @beartype
    def location_name(self, machine_id: MachineId) -> str | None:
        machine = self.machines.get(machine_id)
        if machine is None:
            return None
        stripped = machine.name.strip()
        return stripped or None

    @beartype
    def technician_name(self, technician_id: TechnicianId) -> str | None:
        display_name = self.machines.find_technician_display_name(technician_id)
        if display_name is None:
            return None
        stripped = display_name.strip()
        return stripped or None
