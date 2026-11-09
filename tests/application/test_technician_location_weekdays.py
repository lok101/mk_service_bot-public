from __future__ import annotations

from src.application.sheets.technician_locations import parse_technician_location_rows
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine

_TECH = TechnicianId("001")


def test_vending_machine_service_weekdays_default_empty() -> None:
    machine = VendingMachine(id=MachineId("101"), name="Школа")
    assert machine.service_weekdays == frozenset()


def test_parse_weekday_columns_iso_weekdays() -> None:
    snapshot = parse_technician_location_rows(
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн", "Ср", "Пт"],
            ["101", "Школа", "Иван", "001", "да", "1", "yes"],
        ],
    )
    machine = snapshot.machines_by_technician_id[_TECH][0]
    assert machine.id == MachineId("101")
    assert machine.service_weekdays == frozenset({0, 2, 4})


def test_missing_weekday_columns_yield_empty_service_weekdays() -> None:
    snapshot = parse_technician_location_rows(
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Иван", "001"],
        ],
    )
    machine = snapshot.machines_by_technician_id[_TECH][0]
    assert machine.service_weekdays == frozenset()


def test_inactive_weekday_cell_excluded() -> None:
    snapshot = parse_technician_location_rows(
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника", "вт"],
            ["101", "Школа", "Иван", "001", "нет"],
        ],
    )
    machine = snapshot.machines_by_technician_id[_TECH][0]
    assert machine.service_weekdays == frozenset()
