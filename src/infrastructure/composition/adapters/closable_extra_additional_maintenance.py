from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.service_visits.models import VisitKind, VisitStatus
from src.application.service_visits.ports import ServiceVisitStore
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class ClosableExtraAdditionalMaintenance:
    store: ServiceVisitStore

    @beartype
    def allows(self, machine_id: MachineId, at: datetime) -> bool:
        for visit in self.store.list_for_machine(machine_id, status=VisitStatus.OPEN):
            if visit.kind is VisitKind.EXTRA_INCIDENT and visit.closable:
                return True
        return False
