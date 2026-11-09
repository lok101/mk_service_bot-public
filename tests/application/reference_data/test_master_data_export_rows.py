from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
    MasterDataStores,
    MasterLocation,
    MasterPlacement,
    effective_location_display_name,
)
from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.reference_data.master_data_export import (
    LOCATIONS_DIRECTORY_EXPORT_HEADER,
    MACHINES_MIRROR_EXPORT_HEADER,
    build_locations_directory_export_rows,
    build_machines_mirror_export_rows,
)
from src.application.shared.sheet_cell_format import (
    format_sheet_date,
    format_sheet_decimal,
    parse_sheet_date,
)
from src.domain.ids import MachineId, TechnicianId

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_locations_mirror_header_prefix() -> None:
    expected = [
        "Id",
        "Создание",
        "Снятие",
        "Id торговой точки",
        "Название",
        "Полное имя",
        "Город",
        "Улица",
        "Дом",
        "Широта",
        "Долгота",
    ]
    assert expected == LOCATIONS_DIRECTORY_EXPORT_HEADER
    stores = InMemoryMasterDataStores()
    header, *_ = build_locations_directory_export_rows(stores)
    assert header == expected


def test_locations_export_fills_address_columns() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="МЦ",
            city="Казань",
            street="Фучика",
            house="3",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    _header, *rows = build_locations_directory_export_rows(stores)
    assert len(rows) == 1
    row = rows[0]
    assert row[4] == "МЦ"
    assert row[5] == effective_location_display_name(
        name="МЦ",
        city="Казань",
        street="Фучика",
        house="3",
        display_name="",
    )
    assert row[5] == "МЦ | Фучика, 3"
    assert row[6] == "Казань"
    assert row[7] == "Фучика"
    assert row[8] == "3"

    legacy_display = "МЦ Здоровая семья | Фучика, 3"
    location = stores.locations.list_all()[0]
    stores.locations.upsert(
        MasterLocation(
            location_id=location.location_id,
            name="",
            city="",
            street="",
            house="",
            display_name=legacy_display,
            latitude=None,
            longitude=None,
        )
    )
    _header2, *legacy_rows = build_locations_directory_export_rows(stores)
    legacy = legacy_rows[0]
    assert legacy[4] == ""
    assert legacy[5] == legacy_display
    assert legacy[6] == ""
    assert legacy[7] == ""
    assert legacy[8] == ""


def test_export_locations_history_rows_shape() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="a",
            house="1",
            latitude=Decimal("55.75"),
            longitude=Decimal("37.62"),
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    header, *rows = build_locations_directory_export_rows(stores)
    assert len(rows) >= 1
    joined = "|".join("|".join(r) for r in rows)
    assert format_sheet_decimal(Decimal("55.75")) in joined


def test_export_locations_history_dates_are_sheet_date_only() -> None:
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
    _header, *rows = build_locations_directory_export_rows(stores)
    created = rows[0][1]
    assert created == format_sheet_date(_NOW.date())
    assert parse_sheet_date(created) == _NOW.date()
    assert " " not in created  # не HH:MM:SS


def test_machines_mirror_header_prefix() -> None:
    assert MACHINES_MIRROR_EXPORT_HEADER == [
        "Id",
        "Имя локации",
        "Имя техника",
        "Id техника",
        "Kind",
        "Компания",
    ]


def test_locations_export_sorted_by_location_id_numeric_desc() -> None:
    stores = InMemoryMasterDataStores()
    stores.placements.insert(
        MasterPlacement(
            placement_id="p1",
            machine_id=MachineId("101"),
            location_id="2",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p2",
            machine_id=MachineId("102"),
            location_id="10",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p3",
            machine_id=MachineId("103"),
            location_id="9",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    _header, *rows = build_locations_directory_export_rows(stores)
    assert [row[0] for row in rows] == ["10", "9", "2"]


def test_locations_export_same_location_id_sorts_by_valid_from_desc() -> None:
    stores = InMemoryMasterDataStores()
    older = _NOW.replace(year=2025)
    newer = _NOW
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-old",
            machine_id=MachineId("101"),
            location_id="5",
            valid_from=older,
            valid_to=_NOW,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-new",
            machine_id=MachineId("102"),
            location_id="5",
            valid_from=newer,
            valid_to=None,
        )
    )
    _header, *rows = build_locations_directory_export_rows(stores)
    assert [row[0] for row in rows] == ["5", "5"]
    assert rows[0][1] == format_sheet_date(newer.date())
    assert rows[1][1] == format_sheet_date(older.date())


def test_locations_export_non_numeric_location_ids_after_numeric() -> None:
    stores = InMemoryMasterDataStores()
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-num",
            machine_id=MachineId("101"),
            location_id="3",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-legacy",
            machine_id=MachineId("102"),
            location_id="legacy-a",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-legacy-b",
            machine_id=MachineId("103"),
            location_id="legacy-b",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    _header, *rows = build_locations_directory_export_rows(stores)
    assert [row[0] for row in rows] == ["3", "legacy-a", "legacy-b"]


def test_machines_mirror_company_column_from_names() -> None:
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
    mid = stores.machines.list_all()[0].machine_id
    rows = build_machines_mirror_export_rows(
        stores,
        roster=InMemoryLocationRosterStore(),
        technician_names={},
        company_names={mid: "Орлов М.О."},
    )
    assert rows[0][-1] == "Компания"
    assert rows[1][-1] == "Орлов М.О."


def test_machines_mirror_company_empty_when_missing() -> None:
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
    rows = build_machines_mirror_export_rows(
        stores,
        roster=InMemoryLocationRosterStore(),
        technician_names={},
        company_names={},
    )
    assert rows[1][-1] == ""


def test_machines_mirror_merged_kind_and_sort() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="КофеТочка",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="СнекТочка",
            city="Город",
            street="b",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.SNACK,
            actor_telegram_user_id=1,
        )
    )
    roster = InMemoryLocationRosterStore()
    header, *rows = build_machines_mirror_export_rows(
        stores,
        roster=roster,
        technician_names={},
        company_names={},
    )
    assert header == MACHINES_MIRROR_EXPORT_HEADER
    assert {r[4] for r in rows} == {"coffee", "snack"}
    ids = [r[0] for r in rows]
    assert ids == sorted(ids)
    assert any(r[1] == "КофеТочка | a, 1" and r[4] == "coffee" for r in rows)
    assert any(r[1] == "СнекТочка | b, 1" and r[4] == "snack" for r in rows)


def test_machines_mirror_technician_from_roster() -> None:
    stores = InMemoryMasterDataStores()
    result = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
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
    tid = TechnicianId("7")
    roster = InMemoryLocationRosterStore()
    roster.replace_all(
        (
            LocationRosterEntry(
                machine_id=result.machine_id,
                technician_id=tid,
                service_weekdays=frozenset(),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        )
    )
    _header, *rows = build_machines_mirror_export_rows(
        stores,
        roster=roster,
        technician_names={tid: "Иван"},
        company_names={},
    )
    row = next(r for r in rows if r[0] == result.machine_id.value)
    assert row[2] == "Иван"
    assert row[3] == "7"


def test_machines_mirror_unassigned_empty_tech() -> None:
    stores = InMemoryMasterDataStores()
    result = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
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
    _header, *rows = build_machines_mirror_export_rows(
        stores,
        roster=roster,
        technician_names={},
        company_names={},
    )
    row = next(r for r in rows if r[0] == result.machine_id.value)
    assert row[2] == ""
    assert row[3] == ""


def test_master_data_export_rows_use_reference_data_builder() -> None:
    stores: MasterDataStores = InMemoryMasterDataStores()
    rows = build_machines_mirror_export_rows(
        stores,
        roster=InMemoryLocationRosterStore(),
        technician_names={},
        company_names={},
    )
    assert rows[0] == MACHINES_MIRROR_EXPORT_HEADER


def test_sheets_export_imports_technician_store_from_master_data() -> None:
    source = Path("src/infrastructure/reference_data/master_data_sheets_export.py").read_text(
        encoding="utf-8"
    )
    ports_idx = source.find("from src.application.reference_data.ports import")
    assert ports_idx != -1
    ports_chunk = source[ports_idx : ports_idx + 400]
    assert "TechnicianStore" not in ports_chunk
    assert "from src.application.master_data import" in source
    assert "TechnicianStore" in source
