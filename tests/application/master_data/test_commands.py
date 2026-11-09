from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MasterDataCommandRejected,
    MoveMachineToStorage,
    MoveMachineToStorageInput,
    PlaceMachineFromStorage,
    PlaceMachineFromStorageInput,
    RelocateMachine,
    RelocateMachineInput,
    UpdateLocationAttributes,
    UpdateLocationAttributesInput,
    UpdateMachineSettings,
    UpdateMachineSettingsInput,
    allocate_machine_id,
)
from src.application.master_data.models import (
    LocationIdOverflow,
    MachineKind,
    MachineStatus,
)
from src.domain.ids import MachineId

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_ACTOR = 1001


def test_install_machine_at_location_persists_location_and_machine() -> None:
    stores = InMemoryMasterDataStores()
    result = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе Центр",
            city="Казань",
            street="ул. Ленина",
            house="1",
            latitude=Decimal("55.75"),
            longitude=Decimal("37.62"),
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    assert result.machine_id is not None
    assert result.machine_id == MachineId("101")
    assert result.location_id == "1"
    machine = stores.machines.get(result.machine_id)
    assert machine is not None
    assert machine.status == MachineStatus.ACTIVE_ON_SITE
    assert stores.placements.get_open(result.machine_id) is not None
    assert stores.placements.get_open(result.machine_id).location_id == result.location_id


def test_install_machine_keeps_settings_defaults_true() -> None:
    stores = InMemoryMasterDataStores()
    result = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе Центр",
            city="Казань",
            street="ул. Ленина",
            house="1",
            latitude=Decimal("55.75"),
            longitude=Decimal("37.62"),
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    machine = stores.machines.get(result.machine_id)
    assert machine is not None
    assert machine.include_in_no_sales_monitoring is True
    assert machine.create_visit_on_no_sales is True


def test_install_persists_parts_and_composed_display_name() -> None:
    stores = InMemoryMasterDataStores()
    result = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="МЦ Здоровая семья",
            city="Казань",
            street="Фучика",
            house="3",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    loc = stores.locations.get(result.location_id)
    assert loc is not None
    assert loc.name == "МЦ Здоровая семья"
    assert loc.city == "Казань"
    assert loc.street == "Фучика"
    assert loc.house == "3"
    assert loc.display_name == "МЦ Здоровая семья | Фучика, 3"


def test_install_rejects_incomplete_address_parts() -> None:
    stores = InMemoryMasterDataStores()
    with pytest.raises(MasterDataCommandRejected) as exc:
        InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
            InstallMachineAtLocationInput(
                name="МЦ",
                city="",
                street="Фучика",
                house="3",
                latitude=None,
                longitude=None,
                kind=MachineKind.COFFEE,
                actor_telegram_user_id=_ACTOR,
            )
        )
    assert exc.value.code == "IncompleteLocationAddress"
    assert stores.locations.list_all() == ()


def test_move_and_place_preserve_settings_flags() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    UpdateMachineSettings(stores=stores, now_factory=lambda: _NOW).execute(
        UpdateMachineSettingsInput(
            machine_id=installed.machine_id,
            include_in_no_sales_monitoring=False,
            create_visit_on_no_sales=False,
            include_in_visit_photo_review=True,
            actor_telegram_user_id=_ACTOR,
        )
    )
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(
            machine_id=installed.machine_id,
            actor_telegram_user_id=_ACTOR,
        )
    )
    stored = stores.machines.get(installed.machine_id)
    assert stored is not None
    assert stored.include_in_no_sales_monitoring is False
    assert stored.create_visit_on_no_sales is False
    PlaceMachineFromStorage(stores=stores, now_factory=lambda: _NOW).execute(
        PlaceMachineFromStorageInput(
            machine_id=installed.machine_id,
            name="Y",
            city="Казань",
            street="T",
            house="2",
            latitude=None,
            longitude=None,
            create_new_location=True,
            location_id=None,
            actor_telegram_user_id=_ACTOR,
        )
    )
    placed = stores.machines.get(installed.machine_id)
    assert placed is not None
    assert placed.include_in_no_sales_monitoring is False
    assert placed.create_visit_on_no_sales is False


def test_relocate_creates_new_location_closes_placement() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Старая",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    later = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)
    relocated = RelocateMachine(stores=stores, now_factory=lambda: later).execute(
        RelocateMachineInput(
            machine_id=installed.machine_id,
            name="Новая",
            city="Казань",
            street="T",
            house="2",
            latitude=None,
            longitude=None,
            actor_telegram_user_id=_ACTOR,
        )
    )
    assert relocated.location_id != installed.location_id
    assert relocated.location_id == "2"
    history = stores.placements.list_for_machine(installed.machine_id)
    assert len(history) == 2
    closed = next(p for p in history if p.valid_to is not None)
    assert closed.location_id == installed.location_id
    assert closed.valid_to == later
    open_p = stores.placements.get_open(installed.machine_id)
    assert open_p is not None
    assert open_p.location_id == relocated.location_id


def test_relocate_persists_composed_display_name() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="A",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    result = RelocateMachine(stores=stores, now_factory=lambda: _NOW).execute(
        RelocateMachineInput(
            machine_id=installed.machine_id,
            name="B",
            city="Казань",
            street="Ленина",
            house="2",
            latitude=None,
            longitude=None,
            actor_telegram_user_id=_ACTOR,
        )
    )
    loc = stores.locations.get(result.location_id)
    assert loc is not None
    assert loc.display_name == "B | Ленина, 2"


def test_relocate_location_overflow_keeps_open_placement() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Старая",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    stores.counters.set("location", 999_999)
    with pytest.raises(LocationIdOverflow):
        RelocateMachine(stores=stores, now_factory=lambda: _NOW).execute(
            RelocateMachineInput(
                machine_id=installed.machine_id,
                name="Новая",
                city="Казань",
                street="T",
                house="2",
                latitude=None,
                longitude=None,
                actor_telegram_user_id=_ACTOR,
            )
        )
    open_p = stores.placements.get_open(installed.machine_id)
    assert open_p is not None
    assert open_p.location_id == installed.location_id


def test_update_location_attributes_does_not_touch_placement() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Старое имя",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    before = stores.placements.list_for_machine(installed.machine_id)
    UpdateLocationAttributes(stores=stores, now_factory=lambda: _NOW).execute(
        UpdateLocationAttributesInput(
            location_id=installed.location_id,
            name="Новое имя",
            city="Казань",
            street="ул. 2",
            house="2",
            latitude=None,
            longitude=None,
            actor_telegram_user_id=_ACTOR,
        )
    )
    after = stores.placements.list_for_machine(installed.machine_id)
    assert after == before
    loc = stores.locations.get(installed.location_id)
    assert loc is not None
    assert loc.display_name == "Новое имя | ул. 2, 2"


def test_update_location_rejects_incomplete_parts() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="A",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    with pytest.raises(MasterDataCommandRejected) as exc:
        UpdateLocationAttributes(stores=stores, now_factory=lambda: _NOW).execute(
            UpdateLocationAttributesInput(
                location_id=installed.location_id,
                name="A",
                city="",
                street="S",
                house="1",
                latitude=None,
                longitude=None,
                actor_telegram_user_id=_ACTOR,
            )
        )
    assert exc.value.code == "IncompleteLocationAddress"


def test_update_location_attributes_unknown_id_rejects() -> None:
    stores = InMemoryMasterDataStores()
    with pytest.raises(MasterDataCommandRejected) as exc_info:
        UpdateLocationAttributes(stores=stores, now_factory=lambda: _NOW).execute(
            UpdateLocationAttributesInput(
                location_id="missing",
                name="N",
                city="Казань",
                street="S",
                house="1",
                latitude=None,
                longitude=None,
                actor_telegram_user_id=_ACTOR,
            )
        )
    assert exc_info.value.code == "UnknownLocation"


def test_move_to_storage_sets_in_storage() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.SNACK,
            actor_telegram_user_id=_ACTOR,
        )
    )
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(
            machine_id=installed.machine_id,
            actor_telegram_user_id=_ACTOR,
        )
    )
    machine = stores.machines.get(installed.machine_id)
    assert machine is not None
    assert machine.status == MachineStatus.IN_STORAGE
    assert stores.placements.get_open(installed.machine_id) is None
    placements = stores.placements.list_for_machine(installed.machine_id)
    assert all(p.location_id != "Склад" for p in placements)


def test_place_from_storage_reuses_machine_id() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    mid = installed.machine_id
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(machine_id=mid, actor_telegram_user_id=_ACTOR)
    )
    placed = PlaceMachineFromStorage(stores=stores, now_factory=lambda: _NOW).execute(
        PlaceMachineFromStorageInput(
            machine_id=mid,
            name="Снова",
            city="Казань",
            street="T",
            house="3",
            latitude=None,
            longitude=None,
            create_new_location=True,
            location_id=None,
            actor_telegram_user_id=_ACTOR,
        )
    )
    assert placed.machine_id == mid
    assert stores.machines.get(mid).status == MachineStatus.ACTIVE_ON_SITE
    assert stores.placements.get_open(mid) is not None


def test_place_from_storage_selects_existing_location() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    mid = installed.machine_id
    existing_location_id = installed.location_id
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(machine_id=mid, actor_telegram_user_id=_ACTOR)
    )
    placed = PlaceMachineFromStorage(stores=stores, now_factory=lambda: _NOW).execute(
        PlaceMachineFromStorageInput(
            machine_id=mid,
            name="",
            city="",
            street="",
            house="",
            latitude=None,
            longitude=None,
            create_new_location=False,
            location_id=existing_location_id,
            actor_telegram_user_id=_ACTOR,
        )
    )
    assert placed.machine_id == mid
    assert placed.location_id == existing_location_id
    assert stores.placements.get_open(mid) is not None
    assert stores.placements.get_open(mid).location_id == existing_location_id


def test_place_existing_location_skips_address_fields() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="A",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    MoveMachineToStorage(stores=stores, now_factory=lambda: _NOW).execute(
        MoveMachineToStorageInput(
            machine_id=installed.machine_id,
            actor_telegram_user_id=_ACTOR,
        )
    )
    PlaceMachineFromStorage(stores=stores, now_factory=lambda: _NOW).execute(
        PlaceMachineFromStorageInput(
            machine_id=installed.machine_id,
            create_new_location=False,
            location_id=installed.location_id,
            name="",
            city="",
            street="",
            house="",
            latitude=None,
            longitude=None,
            actor_telegram_user_id=_ACTOR,
        )
    )
    assert stores.placements.get_open(installed.machine_id) is not None


def test_relocate_without_open_placement_rejects() -> None:
    stores = InMemoryMasterDataStores()
    with pytest.raises(MasterDataCommandRejected):
        RelocateMachine(stores=stores, now_factory=lambda: _NOW).execute(
            RelocateMachineInput(
                machine_id=MachineId("101"),
                name="N",
                city="Казань",
                street="S",
                house="1",
                latitude=None,
                longitude=None,
                actor_telegram_user_id=_ACTOR,
            )
        )


def test_place_from_storage_wrong_status_rejects() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    with pytest.raises(MasterDataCommandRejected):
        PlaceMachineFromStorage(stores=stores, now_factory=lambda: _NOW).execute(
            PlaceMachineFromStorageInput(
                machine_id=installed.machine_id,
                name="Y",
                city="Казань",
                street="T",
                house="2",
                latitude=None,
                longitude=None,
                create_new_location=True,
                location_id=None,
                actor_telegram_user_id=_ACTOR,
            )
        )


def test_install_rejects_invalid_latitude() -> None:
    stores = InMemoryMasterDataStores()
    with pytest.raises(MasterDataCommandRejected):
        InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
            InstallMachineAtLocationInput(
                name="X",
                city="Казань",
                street="S",
                house="1",
                latitude=Decimal("100"),
                longitude=Decimal("37"),
                kind=MachineKind.COFFEE,
                actor_telegram_user_id=_ACTOR,
            )
        )


def test_allocate_machine_id_increments_counter() -> None:
    stores = InMemoryMasterDataStores()
    first = allocate_machine_id(stores.counters, MachineKind.COFFEE)
    second = allocate_machine_id(stores.counters, MachineKind.COFFEE)
    assert first != second


def test_audit_records_command() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="X",
            city="Казань",
            street="S",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=_ACTOR,
        )
    )
    audit = stores.audit.list_all()
    assert len(audit) == 1
    assert audit[0].command == "InstallMachineAtLocation"
    assert audit[0].actor_telegram_user_id == _ACTOR
    assert "machine_id" in audit[0].payload
