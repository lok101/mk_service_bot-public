from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.service_visits.detach_on_loading_rollback import (
    DetachVisitTaskOnLoadingRollback,
)
from src.application.service_visits.ports import ServiceVisitStore
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class DetachVisitTaskOnLoadingRollbackAdapter:
    """DetachVisitTaskOnLoadingRollbackPort; composition only (no MM→SV edge)."""

    store: ServiceVisitStore

    @beartype
    def detach(
        self,
        *,
        machine_code: str,
        at: datetime,
        visit_id: str | None,
    ) -> None:
        DetachVisitTaskOnLoadingRollback(store=self.store).execute(
            machine_id=MachineId(machine_code),
            visit_id=visit_id,
            now=at,
        )
