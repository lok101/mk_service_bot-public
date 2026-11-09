from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot


@beartype
def maintenance_cooldown_bypass_expires_at(
    activated_operational_day: date,
    service_calendar_timezone: ZoneInfo,
    *,
    day_end_hour: int,
) -> datetime:
    next_day = activated_operational_day + timedelta(days=1)
    return datetime.combine(
        next_day,
        time(day_end_hour, 0),
        tzinfo=service_calendar_timezone,
    )


@beartype
def is_maintenance_cooldown_bypassed(
    *,
    checked_at: datetime,
    bypass_service_date: date,
    service_calendar_timezone: ZoneInfo,
    day_end_hour: int,
) -> bool:
    expires_at = maintenance_cooldown_bypass_expires_at(
        bypass_service_date,
        service_calendar_timezone,
        day_end_hour=day_end_hour,
    )
    return checked_at < expires_at


@beartype
def is_maintenance_cooldown_active(
    *,
    technician_id: TechnicianId,
    current_machine_id: MachineId,
    checked_at: datetime,
    last_maintenance: TechnicianLastMaintenanceSnapshot | None,
    cooldown_minutes: int,
) -> bool:
    _ = technician_id
    if cooldown_minutes == 0:
        return False
    if last_maintenance is None:
        return False
    if last_maintenance.machine_id == current_machine_id:
        return False
    return checked_at - last_maintenance.completed_at < timedelta(minutes=cooldown_minutes)
