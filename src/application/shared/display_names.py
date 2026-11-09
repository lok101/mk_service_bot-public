from __future__ import annotations

from typing import Literal

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.domain.ids import MachineId, TechnicianId


@beartype
def machine_display_name(
    repository: VendingMachineRepository,
    machine_id: MachineId,
    *,
    missing: Literal["id", "empty"] = "id",
) -> str:
    machine = repository.get(machine_id)
    if missing == "empty":
        return machine.name if machine is not None else ""
    if machine is not None and machine.name.strip():
        return machine.name.strip()
    return machine_id.value


@beartype
def technician_display_name_for_machine(
    repository: VendingMachineRepository,
    machine_id: MachineId,
    *,
    fallback: str,
) -> str:
    display_name = repository.find_technician_display_name_for_machine(machine_id)
    if display_name and display_name.strip():
        return display_name.strip()
    return fallback


@beartype
def technician_display_name(
    repository: VendingMachineRepository,
    technician_id: TechnicianId,
    *,
    fallback: str = "",
) -> str:
    display_name = repository.find_technician_display_name(technician_id)
    if display_name and display_name.strip():
        return display_name.strip()
    return fallback
