from __future__ import annotations

from beartype import beartype

from src.application.master_data import MasterMachineStore
from src.domain.ids import MachineId


@beartype
class MasterMachineNoSalesVisitPolicy:
    def __init__(self, store: MasterMachineStore) -> None:
        self._store = store

    def allows_create_visit_on_no_sales(self, machine_id: MachineId) -> bool:
        machine = self._store.get(machine_id)
        if machine is None:
            return True
        return machine.create_visit_on_no_sales
