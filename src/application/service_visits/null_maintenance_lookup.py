from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.ports import MaintenanceOnOperationalDaySnapshot
from src.domain.ids import MachineId


@beartype
class NullMaintenanceOnOperationalDayLookup:
    @beartype
    def find_earliest_for_operational_day(
        self,
        machine_id: MachineId,
        ops_day: date,
        *,
        timezone: ZoneInfo,
        day_end_hour: int,
    ) -> MaintenanceOnOperationalDaySnapshot | None:
        return None
