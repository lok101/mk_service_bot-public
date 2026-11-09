from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from beartype import beartype

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancy,
    MachineCompanyOccupancyStore,
)
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryMachineCompanyOccupancyStore(MachineCompanyOccupancyStore):
    _by_machine: dict[MachineId, tuple[MachineCompanyOccupancy, ...]] = field(default_factory=dict)

    @beartype
    def replace_for_machine(
        self,
        machine_id: MachineId,
        intervals: Sequence[MachineCompanyOccupancy],
    ) -> None:
        self._by_machine[machine_id] = tuple(intervals)

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[MachineCompanyOccupancy, ...]:
        return self._by_machine.get(machine_id, ())
