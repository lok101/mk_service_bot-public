from __future__ import annotations

from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.state import MachineListState

__all__ = [
    "MachineListDeps",
    "MachineListState",
    "build_machines_dialog",
    "build_machines_router",
]


def __getattr__(name: str) -> object:
    if name == "build_machines_dialog":
        from src.interfaces.telegram.machines.dialog import build_machines_dialog

        return build_machines_dialog
    if name == "build_machines_router":
        from src.interfaces.telegram.machines.router import build_machines_router

        return build_machines_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
