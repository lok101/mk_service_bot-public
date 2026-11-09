from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.service_visits.ports import ServiceVisitStore
from src.interfaces.telegram.machines.deps import MachineDialogDeps


@beartype
@dataclass(frozen=True, slots=True)
class TelegramBundle:
    machine_dialog_deps: MachineDialogDeps
    visit_store: ServiceVisitStore
