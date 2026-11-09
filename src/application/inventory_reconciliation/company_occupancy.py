from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale


@beartype
@dataclass(frozen=True, slots=True)
class MachineCompanyOccupancy:
    machine_id: MachineId
    company_id: int
    valid_from: datetime
    valid_to: datetime | None


@runtime_checkable
class MachineCompanyOccupancyStore(Protocol):
    @beartype
    def replace_for_machine(
        self,
        machine_id: MachineId,
        intervals: Sequence[MachineCompanyOccupancy],
    ) -> None: ...

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[MachineCompanyOccupancy, ...]: ...


@beartype
def rebuild_company_occupancy(
    machine_id: MachineId,
    sales: Sequence[MachineSale],
) -> tuple[MachineCompanyOccupancy, ...]:
    with_company = [sale for sale in sales if sale.company_id is not None]
    ordered = sorted(with_company, key=lambda sale: (sale.occurred_at, sale.source_id))
    if not ordered:
        return ()

    intervals: list[MachineCompanyOccupancy] = []
    current_company_id = ordered[0].company_id
    current_valid_from = ordered[0].occurred_at
    assert current_company_id is not None

    for sale in ordered[1:]:
        sale_company_id = sale.company_id
        assert sale_company_id is not None
        if sale_company_id == current_company_id:
            continue
        valid_to = sale.occurred_at
        if valid_to != current_valid_from:
            intervals.append(
                MachineCompanyOccupancy(
                    machine_id=machine_id,
                    company_id=current_company_id,
                    valid_from=current_valid_from,
                    valid_to=valid_to,
                )
            )
        current_company_id = sale_company_id
        current_valid_from = sale.occurred_at

    intervals.append(
        MachineCompanyOccupancy(
            machine_id=machine_id,
            company_id=current_company_id,
            valid_from=current_valid_from,
            valid_to=None,
        )
    )
    return tuple(intervals)
