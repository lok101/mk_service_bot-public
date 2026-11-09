from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.application.reference_data import (
    ImportLocationRosterFromSheets,
    LocationRosterEntry,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.sheets.technician_locations import parse_technician_location_rows
from src.domain.ids import MachineId, TechnicianId

_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _coffee_rows() -> list[list[str]]:
    return [
        ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн", "Вт"],
        ["101", "Школа", "Иван", "001", "да", ""],
    ]


def test_import_from_full_parser_rows_when_store_empty() -> None:
    store = InMemoryLocationRosterStore()
    use_case = ImportLocationRosterFromSheets(store=store)
    use_case.execute(
        coffee_rows=_coffee_rows(),
        snack_rows=None,
        catalog_machine_count=1,
        now=_NOW,
    )
    entry = store.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("001")
    assert 0 in entry.service_weekdays
    parsed = parse_technician_location_rows(_coffee_rows())
    assert parsed.machines_by_technician_id[TechnicianId("001")][0].service_weekdays == (
        entry.service_weekdays
    )


def test_import_is_noop_when_store_not_empty() -> None:
    store = InMemoryLocationRosterStore()
    store.replace_all(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=None,
                service_weekdays=frozenset(),
                updated_at=_NOW,
                updated_by_telegram_user_id=0,
            ),
        ),
    )
    use_case = ImportLocationRosterFromSheets(store=store)
    use_case.execute(
        coffee_rows=_coffee_rows(),
        snack_rows=None,
        catalog_machine_count=1,
        now=_NOW,
    )
    entry = store.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id is None


def test_import_logs_error_when_catalog_nonempty_and_store_stays_empty(
    caplog: logging.LogCaptureFixture,
) -> None:
    store = InMemoryLocationRosterStore()
    use_case = ImportLocationRosterFromSheets(store=store)
    with caplog.at_level(logging.ERROR):
        use_case.execute(
            coffee_rows=[["Id локации", "Имя локации", "Имя техника", "Id техника"]],
            snack_rows=None,
            catalog_machine_count=3,
            now=_NOW,
        )
    assert store.is_empty() is True
    assert any("location_roster_import" in record.getMessage() for record in caplog.records)
