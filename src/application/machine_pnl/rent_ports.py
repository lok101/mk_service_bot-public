from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.domain.ids import MachineId


@runtime_checkable
class LocationRentOccupancyPort(Protocol):
    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[LocationRentOccupancy, ...]: ...


@runtime_checkable
class RentAccountantAlerter(Protocol):
    @beartype
    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        next_retry_hours: int,
    ) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class FixtureLocationRentCatalog:
    """In-code occupancy/rent fixtures (phase 1 SoT; Sheets adapter later)."""

    occupancies: tuple[LocationRentOccupancy, ...] = ()

    @classmethod
    def default(cls) -> FixtureLocationRentCatalog:
        return cls()

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[LocationRentOccupancy, ...]:
        return tuple(row for row in self.occupancies if row.machine_id == machine_id)
