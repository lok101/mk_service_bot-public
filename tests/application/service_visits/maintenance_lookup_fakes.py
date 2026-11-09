from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.ports import MaintenanceOnOperationalDaySnapshot
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class FakeMaintenanceOnOperationalDayLookup:
    snapshots: dict[tuple[MachineId, date], MaintenanceOnOperationalDaySnapshot]

    @beartype
    def find_earliest_for_operational_day(
        self,
        machine_id: MachineId,
        ops_day: date,
        *,
        timezone: ZoneInfo,
        day_end_hour: int,
    ) -> MaintenanceOnOperationalDaySnapshot | None:
        return self.snapshots.get((machine_id, ops_day))
