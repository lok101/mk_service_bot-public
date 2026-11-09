from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.models import IncidentSource, ServiceVisit, VisitStatus
from src.domain.ids import EventId, MachineId, TechnicianId

__all__ = [
    "LocationDisplayLookup",
    "LocationDisplaySnapshot",
    "MachineSalesQtyBaselineLookup",
    "MachineWeekdaysLookup",
    "MaintenanceOnOperationalDayLookup",
    "MaintenanceOnOperationalDaySnapshot",
    "PlacementAtLookup",
    "PlacementAtSnapshot",
    "RosterEntriesLookup",
    "RosterEntrySnapshot",
    "ServiceVisitStore",
    "TechnicianDisplayLookup",
]


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceOnOperationalDaySnapshot:
    event_id: EventId
    technician_id: TechnicianId
    completed_at: datetime


@runtime_checkable
class ServiceVisitStore(Protocol):
    @beartype
    def get(self, visit_id: str) -> ServiceVisit | None: ...

    @beartype
    def upsert(self, visit: ServiceVisit) -> None: ...

    @beartype
    def delete(self, visit_id: str) -> None: ...

    @beartype
    def list_for_machine(
        self,
        machine_id: MachineId,
        *,
        status: VisitStatus | None = None,
    ) -> list[ServiceVisit]: ...

    @beartype
    def list_open_extras(
        self,
        *,
        incident_source: IncidentSource | None = None,
    ) -> list[ServiceVisit]: ...

    @beartype
    def list_for_due_date_range(
        self,
        *,
        start: date,
        end: date,
    ) -> list[ServiceVisit]: ...


@runtime_checkable
class MachineWeekdaysLookup(Protocol):
    @beartype
    def weekdays_for(self, machine_id: MachineId) -> frozenset[int]: ...


@runtime_checkable
class MaintenanceOnOperationalDayLookup(Protocol):
    @beartype
    def find_earliest_for_operational_day(
        self,
        machine_id: MachineId,
        ops_day: date,
        *,
        timezone: ZoneInfo,
        day_end_hour: int,
    ) -> MaintenanceOnOperationalDaySnapshot | None: ...


@runtime_checkable
class MachineSalesQtyBaselineLookup(Protocol):
    @beartype
    def baseline_avg_qty(
        self,
        *,
        machine_id: MachineId,
        as_of_day: date,
    ) -> Decimal | None:
        """Winsorized mean of like-day daily Σ quantity over SM lookback
        ending before as_of_day. None = insufficient points / unusable.
        """
        ...


@beartype
@dataclass(frozen=True, slots=True)
class PlacementAtSnapshot:
    machine_id: MachineId
    location_id: str
    valid_from: datetime
    valid_to: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class LocationDisplaySnapshot:
    location_id: str
    display_name: str
    address: str


@beartype
@dataclass(frozen=True, slots=True)
class RosterEntrySnapshot:
    machine_id: MachineId
    technician_id: TechnicianId | None
    service_weekdays: frozenset[int]


@runtime_checkable
class PlacementAtLookup(Protocol):
    @beartype
    def placements_for_machine(
        self,
        machine_id: MachineId,
    ) -> tuple[PlacementAtSnapshot, ...]: ...


@runtime_checkable
class LocationDisplayLookup(Protocol):
    @beartype
    def display_for(self, location_id: str) -> LocationDisplaySnapshot | None: ...


@runtime_checkable
class TechnicianDisplayLookup(Protocol):
    @beartype
    def display_name(self, technician_id: TechnicianId) -> str | None: ...


@runtime_checkable
class RosterEntriesLookup(Protocol):
    @beartype
    def list_entries(self) -> tuple[RosterEntrySnapshot, ...]: ...
