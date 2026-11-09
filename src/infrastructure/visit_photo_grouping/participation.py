from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data import MasterMachine
from src.domain.ids import MachineId


@runtime_checkable
class MachineLookup(Protocol):
    @beartype
    def get(self, machine_id: MachineId) -> MasterMachine | None: ...


@beartype
class MasterMachineReviewParticipation:
    def __init__(self, machines: MachineLookup) -> None:
        self._machines = machines

    @beartype
    def include(self, machine_id: str) -> bool:
        machine = self._machines.get(MachineId(machine_id))
        if machine is None:
            return True
        return machine.include_in_visit_photo_review


@beartype
class AlwaysIncluded:
    def include(self, machine_id: str) -> bool:
        return True
