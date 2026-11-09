from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancy,
    MachineCompanyOccupancyStore,
    rebuild_company_occupancy,
)
from src.application.inventory_reconciliation.ports import MachineSalesStore


@beartype
@dataclass(frozen=True, slots=True)
class OccupancyVerifyMismatch:
    machine_id: str
    expected_count: int
    actual_count: int


@beartype
@dataclass(frozen=True, slots=True)
class VerifyOccupancyResult:
    machines_checked: int
    mismatches: tuple[OccupancyVerifyMismatch, ...]


@beartype
def _occupancy_fingerprint(
    intervals: tuple[MachineCompanyOccupancy, ...],
) -> tuple[tuple[int, str, str | None], ...]:
    return tuple(
        (
            interval.company_id,
            interval.valid_from.isoformat(),
            interval.valid_to.isoformat() if interval.valid_to is not None else None,
        )
        for interval in intervals
    )


@beartype
def verify_company_occupancy(
    *,
    sales_store: MachineSalesStore,
    occupancy_store: MachineCompanyOccupancyStore,
) -> VerifyOccupancyResult:
    mismatches: list[OccupancyVerifyMismatch] = []
    machine_ids = sales_store.list_machine_ids_with_sales()
    for machine_id in machine_ids:
        expected = rebuild_company_occupancy(
            machine_id,
            sales_store.list_with_company_id(machine_id),
        )
        actual = occupancy_store.list_for_machine(machine_id)
        if _occupancy_fingerprint(expected) != _occupancy_fingerprint(actual):
            mismatches.append(
                OccupancyVerifyMismatch(
                    machine_id=machine_id.value,
                    expected_count=len(expected),
                    actual_count=len(actual),
                ),
            )
    return VerifyOccupancyResult(
        machines_checked=len(machine_ids),
        mismatches=tuple(mismatches),
    )


@beartype
@dataclass(frozen=True, slots=True)
class RebuildOccupancyResult:
    machines_rebuilt: int


@beartype
def rebuild_company_occupancy_from_sales(
    *,
    sales_store: MachineSalesStore,
    occupancy_store: MachineCompanyOccupancyStore,
) -> RebuildOccupancyResult:
    rebuilt = 0
    for machine_id in sales_store.list_machine_ids_with_sales():
        sales = sales_store.list_with_company_id(machine_id)
        if not sales:
            continue
        intervals = rebuild_company_occupancy(machine_id, sales)
        occupancy_store.replace_for_machine(machine_id, intervals)
        rebuilt += 1
    return RebuildOccupancyResult(machines_rebuilt=rebuilt)
