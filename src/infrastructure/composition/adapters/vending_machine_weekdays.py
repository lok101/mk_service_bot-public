from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class VendingMachineWeekdaysLookup:
    machines: VendingMachineRepository

    @beartype
    def weekdays_for(self, machine_id: MachineId) -> frozenset[int]:
        machine = self.machines.get(machine_id)
        if machine is None:
            return frozenset()
        return machine.service_weekdays
