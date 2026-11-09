from __future__ import annotations

from src.application.master_data import ImportMasterDataFromSheets, InMemoryMasterDataStores
from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    allocate_location_id,
    allocate_machine_id,
)
from src.application.sheets.locations_directory import build_locations_directory_snapshot
from src.application.sheets.technician_locations import parse_technician_location_rows
from src.domain.ids import MachineId

_PARK_HEADER = ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн"]
_DIR_HEADER = [
    "",
    "Создание",
    "Снятие",
    "ТТ",
    "Название",
    "Полное имя",
    "Город",
    "Улица",
    "Дом",
    "Широта",
    "Долгота",
]


def _coffee_park():
    return parse_technician_location_rows(
        [_PARK_HEADER, ["101", "Школа", "", "", ""]],
        assignments="fleet",
    )


def _snack_park():
    return parse_technician_location_rows(
        [_PARK_HEADER, ["501", "ТЦ", "", "", ""]],
        assignments="fleet",
    )


def _directory():
    return build_locations_directory_snapshot(
        [
            _DIR_HEADER,
            [
                "101",
                "01.01.2024",
                "",
                "101",
                "",
                "Школа полн",
                "",
                "",
                "",
                "55,75",
                "37,62",
            ],
            [
                "99",
                "01.01.2023",
                "31.12.2023",
                "101",
                "",
                "Старая",
                "",
                "",
                "",
                "",
                "",
            ],
            [
                "501",
                "01.06.2024",
                "",
                "501",
                "",
                "ТЦ полн",
                "",
                "",
                "",
                "",
                "",
            ],
        ]
    )


def test_import_preserves_machine_ids() -> None:
    stores = InMemoryMasterDataStores()
    result = ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=_directory(),
    )
    assert result.noop is False
    assert stores.machines.get(MachineId("101")) is not None
    assert stores.machines.get(MachineId("501")) is not None
    assert stores.machines.get(MachineId("101")).kind == MachineKind.COFFEE
    assert stores.machines.get(MachineId("501")).kind == MachineKind.SNACK


def test_import_remaps_location_ids() -> None:
    stores = InMemoryMasterDataStores()
    result = ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=_directory(),
    )
    assert set(result.location_id_remap) == {"101", "99", "501"}
    new_ids = set(result.location_id_remap.values())
    assert len(new_ids) == 3
    for new_id in new_ids:
        assert len(new_id) <= 6
        assert stores.locations.get(new_id) is not None
    # sheet location_id мог совпадать с machine code — после remap open placement не обязан = "101"
    open_101 = stores.placements.get_open(MachineId("101"))
    assert open_101 is not None
    assert open_101.location_id == result.location_id_remap["101"]
    assert set(result.location_id_remap.values()) == {"1", "2", "3"}


def test_import_builds_placements() -> None:
    stores = InMemoryMasterDataStores()
    result = ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=_directory(),
    )
    history = stores.placements.list_for_machine(MachineId("101"))
    assert len(history) == 2
    closed = next(p for p in history if p.valid_to is not None)
    assert closed.location_id == result.location_id_remap["99"]
    assert stores.machines.get(MachineId("101")).status == MachineStatus.ACTIVE_ON_SITE


def test_import_sets_counters_max_plus_one() -> None:
    stores = InMemoryMasterDataStores()
    ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=_directory(),
    )
    assert allocate_machine_id(stores.counters, MachineKind.COFFEE).value == "102"
    assert allocate_machine_id(stores.counters, MachineKind.SNACK).value == "502"
    # после трёх location allocate на import следующий — "4"
    assert allocate_location_id(stores.counters) == "4"


def test_import_noop_when_store_not_empty() -> None:
    stores = InMemoryMasterDataStores()
    first = ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=_directory(),
    )
    count = len(stores.machines.list_all())
    second = ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=_directory(),
    )
    assert first.noop is False
    assert second.noop is True
    assert len(stores.machines.list_all()) == count


def test_import_leaves_parts_empty_keeps_display_name() -> None:
    stores = InMemoryMasterDataStores()
    directory = _directory()
    result = ImportMasterDataFromSheets(stores=stores).execute(
        coffee_snapshot=_coffee_park(),
        snack_snapshot=_snack_park(),
        directory=directory,
    )
    assert result.noop is False
    for old_id, new_id in result.location_id_remap.items():
        loaded = stores.locations.get(new_id)
        assert loaded is not None
        assert loaded.name == ""
        assert loaded.city == ""
        assert loaded.street == ""
        assert loaded.house == ""
        assert loaded.display_name == directory.by_location_id[old_id].name
