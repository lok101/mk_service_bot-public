from __future__ import annotations

from src.application.sheets.technician_locations import parse_technician_location_rows
from src.domain.ids import MachineId, TechnicianId


def test_fleet_parse_ignores_technician_and_weekdays() -> None:
    snapshot = parse_technician_location_rows(
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн", "Вт"],
            ["101", "Школа", "Иван", "001", "да", "да"],
        ],
        assignments="fleet",
    )
    assert snapshot.machines_by_technician_id == {}
    assert snapshot.technician_names_by_id == {}
    assert len(snapshot.unassigned_machines) == 1
    machine = snapshot.unassigned_machines[0]
    assert machine.id == MachineId("101")
    assert machine.name == "Школа"
    assert machine.service_weekdays == frozenset()
    assert TechnicianId("001") not in snapshot.machines_by_technician_id


def test_sheet_parse_still_reads_technician_and_weekdays() -> None:
    snapshot = parse_technician_location_rows(
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн"],
            ["101", "Школа", "Иван", "001", "да"],
        ],
    )
    tech = TechnicianId("001")
    assert snapshot.technician_names_by_id[tech] == "Иван"
    machine = snapshot.machines_by_technician_id[tech][0]
    assert machine.service_weekdays == frozenset({0})
    assert snapshot.unassigned_machines == ()
