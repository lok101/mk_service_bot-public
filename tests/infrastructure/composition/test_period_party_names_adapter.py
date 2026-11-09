from __future__ import annotations

from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.infrastructure.composition.adapters.period_party_names import (
    VendingMachinePeriodPartyNamesLookup,
)

_MACHINE_ID = MachineId("vm-01")
_TECHNICIAN_ID = TechnicianId("tech-01")


class _FakeVendingMachineRepository:
    def __init__(
        self,
        *,
        machine: VendingMachine | None = None,
        technician_display_name: str | None = None,
    ) -> None:
        self._machine = machine
        self._technician_display_name = technician_display_name

    def get(self, machine_id: MachineId) -> VendingMachine | None:
        if self._machine is None or self._machine.id != machine_id:
            return None
        return self._machine

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        del technician_id
        return self._technician_display_name

    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None:
        del machine_id
        return None

    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]:
        del technician_id
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        del machine_id
        return None


def test_adapter_location_name_strips_machine_name() -> None:
    adapter = VendingMachinePeriodPartyNamesLookup(
        machines=_FakeVendingMachineRepository(
            machine=VendingMachine(id=_MACHINE_ID, name="  Loc  "),
        ),
    )

    assert adapter.location_name(_MACHINE_ID) == "Loc"


def test_adapter_location_name_returns_none_when_machine_missing() -> None:
    adapter = VendingMachinePeriodPartyNamesLookup(
        machines=_FakeVendingMachineRepository(machine=None),
    )

    assert adapter.location_name(_MACHINE_ID) is None


def test_adapter_location_name_returns_none_when_name_blank() -> None:
    adapter = VendingMachinePeriodPartyNamesLookup(
        machines=_FakeVendingMachineRepository(
            machine=VendingMachine(id=_MACHINE_ID, name="   "),
        ),
    )

    assert adapter.location_name(_MACHINE_ID) is None


def test_adapter_technician_name_from_repository() -> None:
    adapter = VendingMachinePeriodPartyNamesLookup(
        machines=_FakeVendingMachineRepository(technician_display_name="  Tech  "),
    )

    assert adapter.technician_name(_TECHNICIAN_ID) == "Tech"


def test_adapter_technician_name_returns_none_when_missing() -> None:
    adapter = VendingMachinePeriodPartyNamesLookup(
        machines=_FakeVendingMachineRepository(technician_display_name=None),
    )

    assert adapter.technician_name(_TECHNICIAN_ID) is None


def test_adapter_technician_name_returns_none_when_blank() -> None:
    adapter = VendingMachinePeriodPartyNamesLookup(
        machines=_FakeVendingMachineRepository(technician_display_name="   "),
    )

    assert adapter.technician_name(_TECHNICIAN_ID) is None
