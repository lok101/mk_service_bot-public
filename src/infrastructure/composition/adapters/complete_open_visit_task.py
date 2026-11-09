from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.complete_open_visit_task import CompleteOpenVisitTask
from src.application.service_visits.models import VisitTaskSource
from src.application.service_visits.ports import ServiceVisitStore
from src.domain.calendar import operational_day
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class CompleteOpenVisitTaskAdapter:
    """CompleteOpenVisitTaskPort adapter; composition only (no MM→SV application edge)."""

    store: ServiceVisitStore
    timezone: ZoneInfo
    day_end_hour: int

    @beartype
    def complete_open(
        self,
        *,
        machine_code: str,
        at: datetime,
        source: str,
    ) -> str | None:
        ops_day = operational_day(at, self.timezone, self.day_end_hour)
        return CompleteOpenVisitTask(store=self.store).execute(
            machine_id=MachineId(machine_code),
            ops_day=ops_day,
            now=at,
            source=VisitTaskSource(source),
        )
