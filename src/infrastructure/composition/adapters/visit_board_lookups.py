from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.master_data import (
    MasterLocationStore as _MLStore,
)
from src.application.master_data import (
    MasterPlacementStore as _MPStore,
)
from src.application.reference_data.ports import LocationRosterStore
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.service_visits import (
    LocationDisplaySnapshot,
    PlacementAtSnapshot,
    RosterEntrySnapshot,
)
from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class MasterPlacementAtLookup:
    placements: _MPStore

    @beartype
    def placements_for_machine(
        self,
        machine_id: MachineId,
    ) -> tuple[PlacementAtSnapshot, ...]:
        found = sorted(
            self.placements.list_for_machine(machine_id),
            key=lambda item: item.valid_from,
        )
        return tuple(
            PlacementAtSnapshot(
                machine_id=item.machine_id,
                location_id=item.location_id,
                valid_from=item.valid_from,
                valid_to=item.valid_to,
            )
            for item in found
        )


@beartype
@dataclass(frozen=True, slots=True)
class MasterLocationDisplayLookup:
    locations: _MLStore

    @beartype
    def display_for(self, location_id: str) -> LocationDisplaySnapshot | None:
        location = self.locations.get(location_id)
        if location is None:
            return None
        return LocationDisplaySnapshot(
            location_id=location.location_id,
            display_name=location.display_name,
            address=", ".join(part for part in (location.street, location.house) if part),
        )


@beartype
@dataclass(frozen=True, slots=True)
class RosterStoreEntriesLookup:
    roster: LocationRosterStore

    @beartype
    def list_entries(self) -> tuple[RosterEntrySnapshot, ...]:
        return tuple(
            RosterEntrySnapshot(
                machine_id=entry.machine_id,
                technician_id=entry.technician_id,
                service_weekdays=entry.service_weekdays,
            )
            for entry in self.roster.list_all()
        )


@beartype
@dataclass(frozen=True, slots=True)
class TechniciansDirectoryDisplayLookup:
    provider: ReferenceDataProvider

    @beartype
    def display_name(self, technician_id: TechnicianId) -> str | None:
        directory = self.provider.technicians_directory_or_none()
        if directory is None:
            return None
        name = directory.names_by_id.get(technician_id)
        if name is None:
            return None
        stripped = name.strip()
        return stripped or None
