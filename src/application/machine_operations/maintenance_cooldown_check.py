from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import (
    MaintenanceCooldownBypassReader,
    TechnicianLastMaintenanceReader,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.maintenance_cooldown_policy import (
    is_maintenance_cooldown_active,
)


@beartype
def is_maintenance_cooldown_bypass_active(
    *,
    checked_at: datetime,
    bypass_reader: MaintenanceCooldownBypassReader | None,
    service_calendar_timezone: ZoneInfo | None,
) -> bool:
    return (
        bypass_reader is not None
        and service_calendar_timezone is not None
        and bypass_reader.get_active(checked_at=checked_at) is not None
    )


@beartype
def is_cooldown_blocking_new_maintenance(
    *,
    technician_id: TechnicianId,
    machine_id: MachineId,
    checked_at: datetime,
    last_maintenance_reader: TechnicianLastMaintenanceReader,
    cooldown_minutes: int,
    bypass_reader: MaintenanceCooldownBypassReader | None = None,
    service_calendar_timezone: ZoneInfo | None = None,
) -> bool:
    if is_maintenance_cooldown_bypass_active(
        checked_at=checked_at,
        bypass_reader=bypass_reader,
        service_calendar_timezone=service_calendar_timezone,
    ):
        return False
    last = last_maintenance_reader.get_last(technician_id)
    return is_maintenance_cooldown_active(
        technician_id=technician_id,
        current_machine_id=machine_id,
        checked_at=checked_at,
        last_maintenance=last,
        cooldown_minutes=cooldown_minutes,
    )
