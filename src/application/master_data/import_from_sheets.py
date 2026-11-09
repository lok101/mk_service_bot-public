from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from beartype import beartype

from src.application.master_data.models import (
    LOCATION_COUNTER_KEY,
    MACHINE_COFFEE_COUNTER_KEY,
    MACHINE_SNACK_COUNTER_KEY,
    MachineKind,
    MachineStatus,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
)
from src.application.master_data.ports import MasterDataStores
from src.application.sheets import (
    LocationsDirectorySnapshot,
    TechnicianLocationsSnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class ImportMasterDataResult:
    noop: bool
    location_id_remap: dict[str, str]


@beartype
@dataclass(slots=True)
class ImportMasterDataFromSheets:
    stores: MasterDataStores

    @beartype
    def execute(
        self,
        *,
        coffee_snapshot: TechnicianLocationsSnapshot,
        snack_snapshot: TechnicianLocationsSnapshot,
        directory: LocationsDirectorySnapshot,
    ) -> ImportMasterDataResult:
        if not self.stores.locations.is_empty() or not self.stores.machines.is_empty():
            return ImportMasterDataResult(noop=True, location_id_remap={})

        old_location_ids = sorted({placement.location_id for placement in directory.placements})
        location_id_remap = {
            old_id: str(index) for index, old_id in enumerate(old_location_ids, start=1)
        }

        for old_id, new_id in location_id_remap.items():
            source = directory.by_location_id[old_id]
            self.stores.locations.upsert(
                MasterLocation(
                    location_id=new_id,
                    name="",
                    city="",
                    street="",
                    house="",
                    display_name=source.name,
                    latitude=source.latitude,
                    longitude=source.longitude,
                )
            )

        for source in directory.placements:
            self.stores.placements.insert(
                MasterPlacement(
                    placement_id=str(uuid4()),
                    machine_id=source.machine_id,
                    location_id=location_id_remap[source.location_id],
                    valid_from=_date_to_utc_datetime(source.installed_on),
                    valid_to=_optional_date_to_utc_datetime(source.removed_on),
                )
            )

        machines_by_id: dict[MachineId, MachineKind] = {}
        for machine in list_all_machines_from_snapshot(coffee_snapshot):
            machines_by_id[machine.id] = MachineKind.COFFEE
        for machine in list_all_machines_from_snapshot(snack_snapshot):
            machines_by_id[machine.id] = MachineKind.SNACK

        max_coffee: int | None = None
        max_snack: int | None = None
        for machine_id, kind in machines_by_id.items():
            status = (
                MachineStatus.ACTIVE_ON_SITE
                if self.stores.placements.get_open(machine_id) is not None
                else MachineStatus.IN_STORAGE
            )
            self.stores.machines.upsert(
                MasterMachine(
                    machine_id=machine_id,
                    kind=kind,
                    status=status,
                    label=None,
                )
            )
            numeric_id = int(machine_id.value)
            if kind is MachineKind.COFFEE:
                max_coffee = numeric_id if max_coffee is None else max(max_coffee, numeric_id)
            elif kind is MachineKind.SNACK:
                max_snack = numeric_id if max_snack is None else max(max_snack, numeric_id)

        if max_coffee is not None:
            self.stores.counters.set(MACHINE_COFFEE_COUNTER_KEY, max_coffee)
        if max_snack is not None:
            self.stores.counters.set(MACHINE_SNACK_COUNTER_KEY, max_snack)
        self.stores.counters.set(LOCATION_COUNTER_KEY, len(location_id_remap))

        return ImportMasterDataResult(noop=False, location_id_remap=location_id_remap)


@beartype
def _date_to_utc_datetime(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@beartype
def _optional_date_to_utc_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return _date_to_utc_datetime(value)
