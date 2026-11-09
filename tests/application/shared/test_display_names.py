from __future__ import annotations

from src.application.shared.display_names import (
    machine_display_name,
    technician_display_name,
    technician_display_name_for_machine,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine

_MACHINE = MachineId("vm-01")
_TECH = TechnicianId("tech-1")


class _Repo:
    def __init__(
        self,
        *,
        machine: VendingMachine | None,
        tech_for_machine: str | None,
        tech_by_id: str | None,
    ) -> None:
        self._machine = machine
        self._tech_for_machine = tech_for_machine
        self._tech_by_id = tech_by_id

    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return self._machine

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return self._tech_for_machine

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return self._tech_by_id

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


def _repo(
    *,
    machine: VendingMachine | None = None,
    tech_for_machine: str | None = None,
    tech_by_id: str | None = None,
) -> _Repo:
    return _Repo(
        machine=machine,
        tech_for_machine=tech_for_machine,
        tech_by_id=tech_by_id,
    )


def test_machine_display_name_id_strips_name() -> None:
    repo = _repo(machine=VendingMachine(id=_MACHINE, name="  Мега  "))
    assert machine_display_name(repo, _MACHINE) == "Мега"


def test_machine_display_name_id_falls_back_to_value_when_blank() -> None:
    repo = _repo(machine=VendingMachine(id=_MACHINE, name="   "))
    assert machine_display_name(repo, _MACHINE) == "vm-01"


def test_machine_display_name_id_falls_back_when_machine_missing() -> None:
    assert machine_display_name(_repo(machine=None), _MACHINE) == "vm-01"


def test_machine_display_name_empty_returns_raw_name_without_strip() -> None:
    repo = _repo(machine=VendingMachine(id=_MACHINE, name="  Мега  "))
    assert machine_display_name(repo, _MACHINE, missing="empty") == "  Мега  "


def test_machine_display_name_empty_returns_blank_when_machine_missing() -> None:
    assert machine_display_name(_repo(machine=None), _MACHINE, missing="empty") == ""


def test_technician_display_name_for_machine_strips() -> None:
    repo = _repo(tech_for_machine="  Иванов  ")
    assert technician_display_name_for_machine(repo, _MACHINE, fallback="fb") == "Иванов"


def test_technician_display_name_for_machine_whitespace_falls_back() -> None:
    repo = _repo(tech_for_machine="   ")
    assert technician_display_name_for_machine(repo, _MACHINE, fallback="fb") == "fb"


def test_technician_display_name_for_machine_none_falls_back() -> None:
    assert technician_display_name_for_machine(_repo(), _MACHINE, fallback="fb") == "fb"


def test_technician_display_name_strips_and_defaults_to_empty() -> None:
    repo = _repo(tech_by_id="  Петров  ")
    assert technician_display_name(repo, _TECH) == "Петров"


def test_technician_display_name_whitespace_returns_empty() -> None:
    assert technician_display_name(_repo(tech_by_id="   "), _TECH) == ""
