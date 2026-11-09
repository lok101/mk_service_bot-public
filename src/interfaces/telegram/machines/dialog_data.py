from __future__ import annotations

from aiogram_dialog import DialogManager

from src.domain.ids import MachineId


def get_selected_machine_id(dialog_manager: DialogManager) -> MachineId:
    machine_id = dialog_manager.dialog_data.get("machine_id")
    if not isinstance(machine_id, str):
        start_data = dialog_manager.start_data
        if isinstance(start_data, dict):
            fallback = start_data.get("machine_id")
            if isinstance(fallback, str):
                machine_id = fallback
    if not isinstance(machine_id, str):
        raise ValueError("Selected machine id is missing")

    return MachineId(machine_id)
