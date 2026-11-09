from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations import GetServiceCapabilitiesCommand
from src.domain.ids import MachineId
from src.domain.system_user import SystemUser
from src.interfaces.telegram.machines.access import (
    can_use_bot,
    technician_id_for_machine_operations,
)
from src.interfaces.telegram.machines.deps import MachineListDeps

_NO_LAST_SERVICE_LABEL = "нет данных"
_NO_LAST_LOADING_LABEL = "нет данных"


@beartype
def format_service_datetime(value: datetime, timezone: ZoneInfo) -> str:
    localized = value.astimezone(timezone)
    return localized.strftime("%d.%m.%Y %H:%M")


@beartype
def format_last_loading_line(at: datetime | None, timezone: ZoneInfo) -> str:
    if at is None:
        return f"📦 Последняя загрузка: {_NO_LAST_LOADING_LABEL}"
    return f"📦 Последняя загрузка: {format_service_datetime(at, timezone)}"


@beartype
def format_last_service_line(at: datetime | None, timezone: ZoneInfo) -> str:
    if at is None:
        return f"🛠️ Последнее обслуживание: {_NO_LAST_SERVICE_LABEL}"
    return f"🛠️ Последнее обслуживание: {format_service_datetime(at, timezone)}"


@beartype
def last_loading_line_for_machine(deps: MachineListDeps, machine_id: MachineId) -> str:
    aggregate = deps.machine_operations.get(machine_id)
    submitted_at = aggregate.last_loading_submitted_at()
    return format_last_loading_line(submitted_at, deps.service_display_timezone)


@beartype
def last_service_line_for_machine(deps: MachineListDeps, machine_id: MachineId) -> str:
    aggregate = deps.machine_operations.get(machine_id)
    submitted_at = aggregate.last_maintenance_completed_at()
    return format_last_service_line(submitted_at, deps.service_display_timezone)


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceScreenFlags:
    loading_completed: bool
    can_complete_maintenance: bool
    show_maintenance_back: bool


@beartype
def maintenance_screen_flags(
    deps: MachineListDeps,
    *,
    bot_user: SystemUser,
    machine_id: MachineId,
) -> MaintenanceScreenFlags:
    if not can_use_bot(bot_user):
        return MaintenanceScreenFlags(
            loading_completed=False,
            can_complete_maintenance=False,
            show_maintenance_back=False,
        )

    technician_id = technician_id_for_machine_operations(bot_user)
    if technician_id is None:
        return MaintenanceScreenFlags(
            loading_completed=False,
            can_complete_maintenance=False,
            show_maintenance_back=False,
        )

    caps = deps.get_service_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=technician_id,
            machine_id=machine_id,
        ),
    )
    return MaintenanceScreenFlags(
        loading_completed=caps.loading_completed,
        can_complete_maintenance=caps.can_complete_maintenance,
        show_maintenance_back=True,
    )
