from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.application.sheets.locations_directory import (
    build_locations_directory_snapshot,
)
from src.domain.ids import MachineId

_HEADER = [
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


def _dir_row(
    location_id: str,
    created: str,
    removed: str,
    machine: str,
    full_name: str,
    *,
    title: str = "",
    city: str = "",
    street: str = "",
    house: str = "",
    lat: str = "",
    lng: str = "",
) -> list[str]:
    return [
        location_id,
        created,
        removed,
        machine,
        title,
        full_name,
        city,
        street,
        house,
        lat,
        lng,
    ]


def test_parse_locations_directory_happy() -> None:
    snap = build_locations_directory_snapshot(
        [
            _HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "Кафе А — Баумана 1",
                title="Кафе А",
                city="Казань",
                street="Баумана",
                house="1",
                lat="55,8",
                lng="49,1",
            ),
        ],
    )
    placement = snap.by_location_id["loc-a"]
    assert placement.machine_id == MachineId("101")
    assert placement.installed_on == date(2026, 6, 1)
    assert placement.removed_on is None
    assert placement.name == "Кафе А — Баумана 1"
    assert placement.latitude == Decimal("55.8")
    assert placement.longitude == Decimal("49.1")


def test_parse_uses_full_name_not_title() -> None:
    snap = build_locations_directory_snapshot(
        [
            _HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "Полное кафе",
                title="Короткое",
                lat="1",
                lng="2",
            ),
        ],
    )
    assert snap.by_location_id["loc-a"].name == "Полное кафе"


def test_parse_falls_back_to_title_when_full_name_header_absent() -> None:
    header = [
        "",
        "Создание",
        "Снятие",
        "ТТ",
        "Название",
        "Город",
        "Улица",
        "Дом",
        "Широта",
        "Долгота",
    ]
    snap = build_locations_directory_snapshot(
        [
            header,
            ["loc-a", "01.06.2026", "", "101", "Кафе из названия", "", "", "", "1", "2"],
        ],
    )
    assert snap.by_location_id["loc-a"].name == "Кафе из названия"


def test_parse_uses_title_when_full_name_cell_empty() -> None:
    snap = build_locations_directory_snapshot(
        [
            _HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "",
                title="Кафе из названия",
                lat="1",
                lng="2",
            ),
        ],
    )
    assert snap.by_location_id["loc-a"].name == "Кафе из названия"


def test_parse_accepts_nbsp_in_full_name_header() -> None:
    header = list(_HEADER)
    header[5] = "Полное\u00a0имя"
    snap = build_locations_directory_snapshot(
        [
            header,
            _dir_row("loc-a", "01.06.2026", "", "101", "Полное кафе", lat="1", lng="2"),
        ],
    )
    assert snap.by_location_id["loc-a"].name == "Полное кафе"


def test_parse_allows_duplicate_machine_id() -> None:
    snap = build_locations_directory_snapshot(
        [
            _HEADER,
            _dir_row("loc-old", "01.01.2025", "01.06.2026", "101", "Старая", lat="1", lng="2"),
            _dir_row("loc-new", "01.06.2026", "", "101", "Новая", lat="3", lng="4"),
        ],
    )
    assert snap.by_location_id["loc-old"].name == "Старая"
    assert snap.by_location_id["loc-new"].name == "Новая"
    assert snap.by_location_id["loc-old"].machine_id == MachineId("101")
    assert snap.by_location_id["loc-new"].machine_id == MachineId("101")


def test_parse_skips_row_without_ids() -> None:
    snap = build_locations_directory_snapshot(
        [
            _HEADER,
            _dir_row("", "01.06.2026", "", "101", "Без точки", lat="1", lng="2"),
            _dir_row("loc-a", "01.06.2026", "", "", "Без аппарата", lat="1", lng="2"),
            _dir_row("loc-ok", "01.06.2026", "", "101", "Ок", lat="1", lng="2"),
        ],
    )
    assert list(snap.by_location_id) == ["loc-ok"]


def test_parse_allows_empty_name_and_coordinates() -> None:
    snap = build_locations_directory_snapshot(
        [_HEADER, _dir_row("loc-a", "01.06.2026", "", "101", "")],
    )
    placement = snap.by_location_id["loc-a"]
    assert placement.name == ""
    assert placement.latitude is None
    assert placement.longitude is None


def test_parse_accepts_epoch_installed_date() -> None:
    snap = build_locations_directory_snapshot(
        [_HEADER, _dir_row("loc-a", "01.01.1900", "", "101", "С начала", lat="1", lng="2")],
    )
    assert snap.by_location_id["loc-a"].installed_on == date(1900, 1, 1)


def test_parse_ignores_address_and_title_columns() -> None:
    snap = build_locations_directory_snapshot(
        [
            _HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "Кафе полное",
                title="Кафе",
                city="город-не-на-дашборд",
                street="улица",
                house="дом",
                lat="10",
                lng="20",
            ),
        ],
    )
    assert snap.by_location_id["loc-a"].name == "Кафе полное"
    assert not hasattr(snap.by_location_id["loc-a"], "city")


def test_parse_duplicate_location_id_fails() -> None:
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        build_locations_directory_snapshot(
            [
                _HEADER,
                _dir_row("loc-a", "01.06.2025", "", "101", "А", lat="1", lng="2"),
                _dir_row("loc-a", "01.06.2026", "", "102", "Б", lat="3", lng="4"),
            ],
        )


def test_parse_empty_directory_fails() -> None:
    with pytest.raises(ValueError, match="empty|no placement"):
        build_locations_directory_snapshot([_HEADER])


def test_parse_requires_name_and_coordinate_headers() -> None:
    with pytest.raises(ValueError, match="Полное имя|Название|Широта|Долгота|must contain"):
        build_locations_directory_snapshot(
            [["", "Создание", "Снятие", "ТТ"], ["loc-a", "01.06.2026", "", "101"]],
        )


def test_parse_requires_name_or_title_header() -> None:
    with pytest.raises(ValueError, match="Полное имя|Название|must contain"):
        build_locations_directory_snapshot(
            [
                ["", "Создание", "Снятие", "ТТ", "Город", "Широта", "Долгота"],
                ["loc-a", "01.06.2026", "", "101", "Казань", "1", "2"],
            ],
        )


def test_parse_invalid_date_fails() -> None:
    with pytest.raises(ValueError, match="installed_on|date"):
        build_locations_directory_snapshot(
            [_HEADER, _dir_row("loc-a", "not-a-date", "", "101", "А", lat="1", lng="2")],
        )


def test_parse_invalid_coordinate_fails() -> None:
    with pytest.raises(ValueError, match="latitude|decimal"):
        build_locations_directory_snapshot(
            [_HEADER, _dir_row("loc-a", "01.06.2026", "", "101", "А", lat="abc", lng="2")],
        )
