from __future__ import annotations

from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.dialog import build_machines_dialog
from src.interfaces.telegram.machines.router import build_machines_router
from src.interfaces.telegram.machines.state import MachineListState

__all__ = [
    "MachineListDeps",
    "MachineListState",
    "build_machines_dialog",
    "build_machines_router",
]
