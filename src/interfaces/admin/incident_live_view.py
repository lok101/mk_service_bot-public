from __future__ import annotations

from beartype import beartype

from src.application.master_data import MasterDataStores
from src.domain.ids import MachineId
from src.interfaces.admin.master_data_view import machine_profile_display_name

__all__ = ["incident_machine_screen_name", "live_incident_choices"]


@beartype
def incident_machine_screen_name(stores: MasterDataStores | None, machine_id: str) -> str:
    if stores is None:
        return "—"
    machine = stores.machines.get(MachineId(machine_id))
    if machine is None:
        return "—"
    name = machine_profile_display_name(stores, machine)
    code = machine.machine_id.value
    if name == code or name == f"[склад] {code}":
        return "—"
    return name


@beartype
def live_incident_choices(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=str.casefold))
