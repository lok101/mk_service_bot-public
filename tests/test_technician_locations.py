from __future__ import annotations

import pytest

from src.application.sheets.technician_locations import (
    build_technician_locations_snapshot,
    find_technician_display_name_for_machine_in_snapshot,
    find_technician_id_for_machine_in_snapshot,
    list_all_machines_from_snapshot,
    parse_technician_location_rows,
)
from src.domain.ids import MachineId, TechnicianId


@pytest.fixture
def technician_location_rows() -> list[list[str]]:
    return [
        ["Id локации", "Имя локации", "Имя техника", "Id техника"],
        [
            "101",
            "ТЦ Комсомолл, 3 эт | Сибирский тракт, 2",
            "Илья",
            "001",
        ],
        [
            "102",
            "МЦ Здоровая семья | Фучика, 3",
            "Иван",
            "011",
        ],
        [
            "103",
            "ТЦ Комсомолл, 1 эт | Сибирский тракт, 2",
            "Илья",
            "001",
        ],
        [
            "104",
            "Оками Металлургов | Металлургов, 82",
            "Данил",
            "003",
        ],
    ]


def test_parse_technician_location_rows_groups_by_technician_id(
    technician_location_rows: list[list[str]],
) -> None:
    snapshot = parse_technician_location_rows(technician_location_rows)

    assert snapshot.technician_names_by_id == {
        TechnicianId("001"): "Илья",
        TechnicianId("011"): "Иван",
        TechnicianId("003"): "Данил",
    }
    assert [machine.id for machine in snapshot.machines_by_technician_id[TechnicianId("001")]] == [
        MachineId("101"),
        MachineId("103"),
    ]
    assert snapshot.machines_by_technician_id[TechnicianId("001")][0].name.startswith(
        "ТЦ Комсомолл, 3 эт",
    )
    assert [machine.id for machine in snapshot.machines_by_technician_id[TechnicianId("003")]] == [
        MachineId("104"),
    ]


def test_build_technician_locations_snapshot(
    technician_location_rows: list[list[str]],
) -> None:
    snapshot = build_technician_locations_snapshot(technician_location_rows)

    ilya_locations = snapshot.machines_by_technician_id[TechnicianId("001")]
    danil_locations = snapshot.machines_by_technician_id[TechnicianId("003")]
    ivan_locations = snapshot.machines_by_technician_id[TechnicianId("011")]

    assert [machine.id for machine in ilya_locations] == [
        MachineId("101"),
        MachineId("103"),
    ]
    assert [machine.id for machine in danil_locations] == [MachineId("104")]
    assert [machine.id for machine in ivan_locations] == [MachineId("102")]


def test_parse_technician_location_rows_raises_on_duplicate_location_ids() -> None:
    rows = [
        ["Id локации", "Имя локации", "Имя техника", "Id техника"],
        ["101", "Location A", "Илья", "001"],
        ["101", "Location B", "Данил", "003"],
    ]

    with pytest.raises(ValueError, match="Duplicate location id"):
        parse_technician_location_rows(rows)


def test_parse_technician_location_rows_raises_on_conflicting_technician_names() -> None:
    rows = [
        ["Id локации", "Имя локации", "Имя техника", "Id техника"],
        ["101", "Location A", "Илья", "001"],
        ["102", "Location B", "Пётр", "001"],
    ]

    with pytest.raises(ValueError, match="Conflicting technician names"):
        parse_technician_location_rows(rows)


def test_list_all_machines_from_snapshot_returns_unique_machines(
    technician_location_rows: list[list[str]],
) -> None:
    snapshot = build_technician_locations_snapshot(technician_location_rows)

    machines = list_all_machines_from_snapshot(snapshot)

    assert {machine.id for machine in machines} == {
        MachineId("101"),
        MachineId("102"),
        MachineId("103"),
        MachineId("104"),
    }


def test_find_technician_id_for_machine_in_snapshot(
    technician_location_rows: list[list[str]],
) -> None:
    snapshot = build_technician_locations_snapshot(technician_location_rows)

    assert find_technician_id_for_machine_in_snapshot(
        snapshot,
        MachineId("103"),
    ) == TechnicianId("001")
    assert find_technician_id_for_machine_in_snapshot(
        snapshot,
        MachineId("102"),
    ) == TechnicianId("011")
    assert (
        find_technician_id_for_machine_in_snapshot(
            snapshot,
            MachineId("999"),
        )
        is None
    )


def test_find_technician_display_name_for_machine_in_snapshot(
    technician_location_rows: list[list[str]],
) -> None:
    snapshot = build_technician_locations_snapshot(technician_location_rows)

    assert (
        find_technician_display_name_for_machine_in_snapshot(
            snapshot,
            MachineId("103"),
        )
        == "Илья"
    )
    assert (
        find_technician_display_name_for_machine_in_snapshot(
            snapshot,
            MachineId("999"),
        )
        is None
    )


def test_parse_technician_location_rows_allows_location_without_technician() -> None:
    rows = [
        ["Id локации", "Имя локации", "Имя техника", "Id техника"],
        ["101", "Location A", "", ""],
        ["102", "Location B", "Илья", "001"],
    ]

    snapshot = parse_technician_location_rows(rows)

    assert list(snapshot.machines_by_technician_id) == [TechnicianId("001")]
    assert [machine.id for machine in snapshot.machines_by_technician_id[TechnicianId("001")]] == [
        MachineId("102"),
    ]


def test_parse_includes_unassigned_in_list_all() -> None:
    rows = [
        ["Id локации", "Имя локации", "Имя техника", "Id техника"],
        ["101", "Location A", "", ""],
        ["102", "Location B", "Илья", "001"],
    ]
    snapshot = parse_technician_location_rows(rows)
    ids = {m.id.value for m in list_all_machines_from_snapshot(snapshot)}
    assert ids == {"101", "102"}
    assert [m.id.value for m in snapshot.unassigned_machines] == ["101"]


def test_parse_technician_location_rows_raises_on_technician_name_without_id() -> None:
    rows = [
        ["Id локации", "Имя локации", "Имя техника", "Id техника"],
        ["101", "Location A", "Илья", ""],
    ]

    with pytest.raises(ValueError, match="Technician id is missing"):
        parse_technician_location_rows(rows)
