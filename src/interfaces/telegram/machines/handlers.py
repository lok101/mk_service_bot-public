from __future__ import annotations

from dataclasses import dataclass

from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.handlers_common import CommonHandlersMixin
from src.interfaces.telegram.machines.handlers_loading_photos import LoadingPhotosHandlersMixin
from src.interfaces.telegram.machines.handlers_maintenance import MaintenanceHandlersMixin
from src.interfaces.telegram.machines.handlers_micromarket_checklist import (
    MicromarketChecklistHandlersMixin,
)
from src.interfaces.telegram.machines.handlers_micromarket_inventory import (
    MicromarketInventoryHandlersMixin,
)
from src.interfaces.telegram.machines.handlers_selection import SelectionHandlersMixin
from src.interfaces.telegram.machines.handlers_snack_inventory import (
    SnackInventoryHandlersMixin,
)


@dataclass
class MachineListHandlers(
    SelectionHandlersMixin,
    MaintenanceHandlersMixin,
    LoadingPhotosHandlersMixin,
    SnackInventoryHandlersMixin,
    MicromarketInventoryHandlersMixin,
    MicromarketChecklistHandlersMixin,
    CommonHandlersMixin,
):
    deps: MachineListDeps
