from __future__ import annotations

from datetime import UTC, datetime

from src.application.inventory_reconciliation import MachineCompanyOccupancy
from src.domain.ids import MachineId
from src.infrastructure.composition.factories.current_company_names import (
    build_machine_company_names,
)
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)


def test_build_machine_company_names_from_open_occupancy() -> None:
    mid = MachineId("vm-01")
    occ = InMemoryMachineCompanyOccupancyStore()
    occ.replace_for_machine(
        mid,
        (MachineCompanyOccupancy(mid, 7, datetime(2026, 1, 1, tzinfo=UTC), None),),
    )
    names = build_machine_company_names(
        occupancy_store=occ,
        display_names={7: "Орлов М.О."},
        machine_ids=(mid,),
    )
    assert names == {mid: "Орлов М.О."}


def test_build_machine_company_names_empty_without_occupancy() -> None:
    mid = MachineId("vm-01")
    occ = InMemoryMachineCompanyOccupancyStore()
    names = build_machine_company_names(
        occupancy_store=occ,
        display_names={7: "X"},
        machine_ids=(mid,),
    )
    assert names == {mid: ""}
