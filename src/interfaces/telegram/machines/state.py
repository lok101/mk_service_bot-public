from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MachineListState(StatesGroup):
    machines = State()
    workspace = State()
    snack_inventory = State()
    loading_photos = State()
    maintenance = State()
    admin_maintenance = State()
