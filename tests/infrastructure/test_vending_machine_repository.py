from __future__ import annotations

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.sheets import TechnicianLocationsSnapshot
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.infrastructure.integrations.google.sheets.vending_machine_repository import (
    GoogleSheetsVendingMachineRepository,
)

_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_DIR_HEADER = ["Id", "Имя"]
_ROW = ["129", "Локация 1", "Иван", "tech-1"]


def _machine_snap(
    machine_id: str,
    *,
    name: str,
    tech_id: str | None = None,
    tech_name: str | None = None,
    weekdays: frozenset[int] = frozenset(),
) -> TechnicianLocationsSnapshot:
    machine = VendingMachine(
        id=MachineId(machine_id),
        name=name,
        service_weekdays=weekdays,
    )
    if tech_id is None:
        return TechnicianLocationsSnapshot(
            machines_by_technician_id={},
            technician_names_by_id={},
            unassigned_machines=(machine,),
        )
    technician_id = TechnicianId(tech_id)
    return TechnicianLocationsSnapshot(
        machines_by_technician_id={technician_id: (machine,)},
        technician_names_by_id={technician_id: tech_name or tech_id},
        unassigned_machines=(),
    )


def _repo(rows: list[list[str]] | None = None) -> GoogleSheetsVendingMachineRepository:
    provider = ReferenceDataProvider()
    if rows is not None:
        provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, rows)
    return GoogleSheetsVendingMachineRepository(provider=provider)


def test_list_available_for_technician_returns_machines() -> None:
    repo = _repo([_HEADER, _ROW])
    machines = repo.list_available_for_technician(TechnicianId("tech-1"))
    assert [machine.id for machine in machines] == [MachineId("129")]


def test_degraded_returns_empty_list() -> None:
    repo = _repo(None)
    assert repo.list_available_for_technician(TechnicianId("tech-1")) == []
    assert repo.list_all() == []


def test_find_technician_returns_none_when_degraded() -> None:
    repo = _repo(None)
    assert repo.find_technician_id_for_machine(MachineId("129")) is None
    assert repo.get(MachineId("129")) is None


def test_list_available_includes_assigned_micromarket() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap("129", name="Cafe", tech_id="tech-1", tech_name="Иван"),
        snack=None,
        micromarket=_machine_snap("701", name="Fridge", tech_id="tech-1", tech_name="Иван"),
        locations_directory=None,
    )
    repo = GoogleSheetsVendingMachineRepository(provider=provider)
    machines = repo.list_available_for_technician(TechnicianId("tech-1"))
    ids = {m.id.value for m in machines}
    assert ids == {"129", "701"}
    assert repo.get(MachineId("701")) is not None
    assert repo.find_technician_id_for_machine(MachineId("701")) == TechnicianId("tech-1")


def test_list_available_excludes_unassigned_micromarket() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap("129", name="Cafe", tech_id="tech-1", tech_name="Иван"),
        snack=None,
        micromarket=_machine_snap("701", name="Fridge"),
        locations_directory=None,
    )
    repo = GoogleSheetsVendingMachineRepository(provider=provider)
    machines = repo.list_available_for_technician(TechnicianId("tech-1"))
    ids = {m.id.value for m in machines}
    assert ids == {"129"}
    assert "701" not in ids


def test_list_all_includes_micromarket_excludes_snack() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap("129", name="Cafe", tech_id="tech-1", tech_name="Иван"),
        snack=_machine_snap("501", name="Snack", tech_id="tech-1", tech_name="Иван"),
        micromarket=_machine_snap("701", name="Fridge", tech_id="tech-1", tech_name="Иван"),
        locations_directory=None,
    )
    repo = GoogleSheetsVendingMachineRepository(provider=provider)
    ids = {m.id.value for m in repo.list_all()}
    assert ids == {"129", "701"}
    assert "501" not in ids


def test_vending_repo_display_name_from_directory() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, ["165", "ФОК", "Егор", "10017"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [_DIR_HEADER, ["10003", "Данил"], ["10017", "Егор"]],
    )
    repo = GoogleSheetsVendingMachineRepository(provider=provider)
    assert repo.find_technician_display_name(TechnicianId("10003")) == "Данил"
    # historical tech not on locations still resolves
    assert repo.find_technician_id_for_machine(MachineId("165")) == TechnicianId("10017")


def test_vending_repo_for_machine_uses_directory_name() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, ["165", "ФОК", "WrongName", "10017"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [_DIR_HEADER, ["10017", "Егор"]],
    )
    repo = GoogleSheetsVendingMachineRepository(provider=provider)
    assert repo.find_technician_display_name_for_machine(MachineId("165")) == "Егор"
