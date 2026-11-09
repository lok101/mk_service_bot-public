from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.sheets.technician_locations import list_all_machines_from_snapshot
from src.domain.ids import MachineId, TechnicianId

_NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_COFFEE_ROWS = [
    ["Id локации", "Имя локации", "Имя техника", "Id техника", "Пн", "Вт"],
    ["101", "Школа", "Алексей", "A", "да", ""],
]


def test_overlay_replaces_sheet_assignment_and_weekdays() -> None:
    store = InMemoryLocationRosterStore()
    store.replace_all(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("B"),
                service_weekdays=frozenset({1}),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        ),
    )
    provider = ReferenceDataProvider()
    provider.configure_roster(enabled=True, store=store)
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["B", "Борис"]],
    )
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, _COFFEE_ROWS)
    snapshot = provider.coffee_locations()
    assert TechnicianId("A") not in snapshot.machines_by_technician_id
    machines = snapshot.machines_by_technician_id[TechnicianId("B")]
    assert machines[0].id == MachineId("101")
    assert machines[0].service_weekdays == frozenset({1})
    assert snapshot.technician_names_by_id[TechnicianId("B")] == "Борис"


def test_missing_roster_row_is_unassigned_empty_weekdays() -> None:
    provider = ReferenceDataProvider()
    provider.configure_roster(enabled=True, store=InMemoryLocationRosterStore())
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, _COFFEE_ROWS)
    snapshot = provider.coffee_locations()
    machines = list_all_machines_from_snapshot(snapshot)
    assert machines[0].service_weekdays == frozenset()
    assert snapshot.unassigned_machines[0].id == MachineId("101")


def test_orphan_roster_row_does_not_create_machine() -> None:
    store = InMemoryLocationRosterStore()
    store.replace_all(
        (
            LocationRosterEntry(
                machine_id=MachineId("999"),
                technician_id=TechnicianId("B"),
                service_weekdays=frozenset({0}),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        ),
    )
    provider = ReferenceDataProvider()
    provider.configure_roster(enabled=True, store=store)
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, _COFFEE_ROWS)
    ids = {m.id.value for m in list_all_machines_from_snapshot(provider.coffee_locations())}
    assert ids == {"101"}


def test_fleet_merge_ignores_technician_name_conflict() -> None:
    provider = ReferenceDataProvider()
    provider.configure_roster(enabled=True, store=InMemoryLocationRosterStore())
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Кофе", "ИмяА", "T1"],
        ],
    )
    provider.apply_rows(
        ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["501", "Снек", "ИмяБ", "T1"],
        ],
    )
    catalog = provider.locations_catalog()
    ids = {m.id.value for m in list_all_machines_from_snapshot(catalog)}
    assert ids == {"101", "501"}
