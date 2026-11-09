from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MoveMachineToStorage,
    MoveMachineToStorageInput,
    hydrate_provider_from_master_data,
)
from src.application.master_data.models import MachineKind
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.sheets import (
    LocationPlacement,
    LocationsDirectorySnapshot,
    TechnicianLocationsSnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import MachineId
from src.domain.models import VendingMachine

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_STALE_SNACK_ID = MachineId("501")
_STALE_LOCATION_ID = "LKGLOC"


def test_hydrate_provider_from_master_data_builds_snapshots() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=Decimal("55.75"),
            longitude=Decimal("37.62"),
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    catalog = provider.locations_catalog()
    machines = list(catalog.unassigned_machines) + [
        m for ms in catalog.machines_by_technician_id.values() for m in ms
    ]
    assert any(m.id == installed.machine_id for m in machines)
    directory = provider.locations_directory_or_none()
    assert directory is not None
    assert directory.placements


def test_provider_machine_name_is_current_location() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе Центр",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    machine = next(
        m for m in provider.locations_catalog().unassigned_machines if m.id == installed.machine_id
    )
    assert machine.name == "Кафе Центр | ул. 1, 1"


def test_provider_in_storage_display_marker() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(machine_id=installed.machine_id, actor_telegram_user_id=1)
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    machine = next(
        m for m in provider.locations_catalog().unassigned_machines if m.id == installed.machine_id
    )
    assert machine.name == f"[склад] {installed.machine_id.value}"


def test_hydrate_micromarket_in_catalog_and_service_not_coffee() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Холод",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.MICRO_MARKET,
            actor_telegram_user_id=1,
        )
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    catalog_ids = {
        m.id.value for m in list_all_machines_from_snapshot(provider.locations_catalog())
    }
    service_ids = {
        m.id.value for m in list_all_machines_from_snapshot(provider.service_locations())
    }
    coffee_ids = {m.id.value for m in list_all_machines_from_snapshot(provider.coffee_locations())}
    assert installed.machine_id.value in catalog_ids
    assert installed.machine_id.value in service_ids
    assert installed.machine_id.value not in coffee_ids


def test_hydrate_micromarket_in_storage_display_name() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.MICRO_MARKET,
            actor_telegram_user_id=1,
        )
    )
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(machine_id=installed.machine_id, actor_telegram_user_id=1)
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    machine = next(
        m for m in provider.locations_catalog().unassigned_machines if m.id == installed.machine_id
    )
    assert machine.name == f"[склад] {installed.machine_id.value}"


def test_hydrate_passes_empty_micromarket_when_none_in_park() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    assert provider._micromarket_locations is not None
    assert list_all_machines_from_snapshot(provider._micromarket_locations) == []


def test_roster_overlay_still_applies_after_master_hydrate() -> None:
    from src.application.reference_data.location_roster import LocationRosterEntry
    from src.application.reference_data.location_roster_memory import (
        InMemoryLocationRosterStore,
    )
    from src.application.reference_data.models import ReferenceDataSourceId
    from src.domain.ids import TechnicianId

    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    roster = InMemoryLocationRosterStore()
    roster.replace_all(
        (
            LocationRosterEntry(
                machine_id=installed.machine_id,
                technician_id=TechnicianId("B"),
                service_weekdays=frozenset({1}),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        ),
    )
    provider = ReferenceDataProvider()
    provider.configure_roster(enabled=True, store=roster)
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["B", "Борис"]],
    )
    hydrate_provider_from_master_data(provider, stores)
    snapshot = provider.coffee_locations()
    machines = snapshot.machines_by_technician_id[TechnicianId("B")]
    assert machines[0].id == installed.machine_id
    assert machines[0].service_weekdays == frozenset({1})
    assert machines[0].name == "Кафе | a, 1"


def test_hydrate_clears_stale_kind_when_master_has_only_coffee() -> None:
    stale_snack = TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=(
            VendingMachine(
                id=_STALE_SNACK_ID,
                name="Stale Snack",
                service_weekdays=frozenset(),
            ),
        ),
    )
    stale_placement = LocationPlacement(
        location_id=_STALE_LOCATION_ID,
        machine_id=_STALE_SNACK_ID,
        installed_on=date(2026, 1, 1),
        removed_on=None,
        name="Stale Loc",
        latitude=None,
        longitude=None,
    )
    stale_directory = LocationsDirectorySnapshot(
        placements=(stale_placement,),
        by_location_id={_STALE_LOCATION_ID: stale_placement},
    )

    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=None,
        snack=stale_snack,
        locations_directory=stale_directory,
    )

    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )

    hydrate_provider_from_master_data(provider, stores)

    snack = provider._snack_locations
    assert snack is not None
    snack_ids = {m.id for m in snack.unassigned_machines}
    for machines in snack.machines_by_technician_id.values():
        snack_ids.update(m.id for m in machines)
    assert _STALE_SNACK_ID not in snack_ids
    assert snack_ids == set()

    catalog = provider.locations_catalog()
    catalog_ids = {m.id for m in catalog.unassigned_machines}
    for machines in catalog.machines_by_technician_id.values():
        catalog_ids.update(m.id for m in machines)
    assert _STALE_SNACK_ID not in catalog_ids

    directory = provider.locations_directory_or_none()
    assert directory is not None
    assert _STALE_LOCATION_ID not in directory.by_location_id
    assert all(p.location_id != _STALE_LOCATION_ID for p in directory.placements)
