from __future__ import annotations

from dataclasses import dataclass, field

from src.application.machine_operations.services import ListAvailableMachinesService
from src.application.machine_operations.use_cases import (
    ListAvailableMachinesQuery,
    LocationListScope,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.domain.system_user import BotRole


@dataclass
class _FakeVendingMachineRepository:
    machines_by_technician_id: dict[TechnicianId, list[VendingMachine]] = field(
        default_factory=lambda: {
            TechnicianId("001"): [
                VendingMachine(id=MachineId("101"), name="Location 101"),
            ],
            TechnicianId("003"): [
                VendingMachine(id=MachineId("104"), name="Location 104"),
            ],
        },
    )

    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        return list(self.machines_by_technician_id.get(technician_id, ()))

    def list_all(self) -> list[VendingMachine]:
        machines_by_id: dict[MachineId, VendingMachine] = {}
        for machines in self.machines_by_technician_id.values():
            for machine in machines:
                machines_by_id[machine.id] = machine
        return list(machines_by_id.values())

    def find_technician_id_for_machine(
        self,
        machine_id: MachineId,
    ) -> TechnicianId | None:
        for technician_id, machines in self.machines_by_technician_id.items():
            if any(machine.id == machine_id for machine in machines):
                return technician_id
        return None

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        technician_id = self.find_technician_id_for_machine(machine_id)
        if technician_id is None:
            return None
        return f"Technician {technician_id.value}"

    def find_technician_display_name(
        self,
        technician_id: TechnicianId,
    ) -> str | None:
        return f"Technician {technician_id.value}"

    def get(self, machine_id: MachineId) -> VendingMachine | None:
        for machines in self.machines_by_technician_id.values():
            for machine in machines:
                if machine.id == machine_id:
                    return machine
        return None


def test_list_available_machines_for_administrator_returns_all() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(role=BotRole.ADMINISTRATOR),
    )

    assert {machine.id for machine in machines} == {MachineId("101"), MachineId("104")}


def test_list_available_machines_for_technician_returns_assigned_only() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.TECHNICIAN,
            technician_id=TechnicianId("001"),
        ),
    )

    assert len(machines) == 1
    assert machines[0].id == MachineId("101")


def test_list_available_machines_for_technician_without_id_returns_empty() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(role=BotRole.TECHNICIAN),
    )

    assert machines == []


def test_list_available_machines_for_technician_others_scope() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.TECHNICIAN,
            technician_id=TechnicianId("001"),
            scope=LocationListScope.OTHERS,
        ),
    )

    assert len(machines) == 1
    assert machines[0].id == MachineId("104")


def test_list_available_machines_for_administrator_with_technician_id_own_scope() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.ADMINISTRATOR,
            technician_id=TechnicianId("001"),
            scope=LocationListScope.OWN,
        ),
    )

    assert len(machines) == 1
    assert machines[0].id == MachineId("101")


def test_list_available_machines_for_administrator_with_technician_id_others_scope() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.ADMINISTRATOR,
            technician_id=TechnicianId("001"),
            scope=LocationListScope.OTHERS,
        ),
    )

    assert len(machines) == 1
    assert machines[0].id == MachineId("104")


def test_list_available_machines_for_administrator_ignores_scope_without_technician_id() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())

    machines = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.ADMINISTRATOR,
            scope=LocationListScope.OTHERS,
        ),
    )

    assert {machine.id for machine in machines} == {MachineId("101"), MachineId("104")}


def test_list_machines_empty_for_none_role() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())
    result = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.NONE,
            technician_id=None,
            scope=LocationListScope.OWN,
        )
    )
    assert result == []


def test_list_machines_empty_for_none_role_with_technician_id() -> None:
    service = ListAvailableMachinesService(repository=_FakeVendingMachineRepository())
    result = service.execute(
        ListAvailableMachinesQuery(
            role=BotRole.NONE,
            technician_id=TechnicianId("001"),
            scope=LocationListScope.OWN,
        )
    )
    assert result == []
