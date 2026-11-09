from __future__ import annotations

from aiogram.fsm.state import State
from beartype import beartype

from src.application.machine_operations import (
    ListAvailableMachinesQuery,
    LocationListScope,
)
from src.domain.ids import TechnicianId
from src.domain.models import VendingMachine
from src.domain.system_user import BotRole, SystemUser
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.state import MachineListState


@beartype
def technician_id_for_machine_operations(
    bot_user: SystemUser | None,
) -> TechnicianId | None:
    if bot_user is None:
        return None

    return bot_user.technician_id


@beartype
def can_use_bot(bot_user: SystemUser) -> bool:
    if bot_user.role is BotRole.NONE:
        return False
    return bot_user.is_active


@beartype
def can_show_machine_list(bot_user: SystemUser) -> bool:
    if not can_use_bot(bot_user):
        return False

    if bot_user.role is BotRole.ADMINISTRATOR:
        return True

    return bot_user.technician_id is not None


@beartype
def maintenance_state_for_bot_user(bot_user: SystemUser | None) -> State:
    if bot_user is not None and bot_user.role is BotRole.ADMINISTRATOR:
        return MachineListState.admin_maintenance

    return MachineListState.maintenance


@beartype
def requires_revision_check_before_maintenance(bot_user: SystemUser | None) -> bool:
    if bot_user is None:
        return True

    if bot_user.role is BotRole.NONE:
        return True

    if bot_user.role is BotRole.TECHNICIAN:
        return True

    if bot_user.role is BotRole.ADMINISTRATOR:
        return bot_user.technician_id is not None

    return True


@beartype
def list_machines_for_bot_user(
    deps: MachineListDeps,
    bot_user: SystemUser,
    *,
    scope: LocationListScope = LocationListScope.OWN,
) -> list[VendingMachine]:
    return deps.list_available_machines.execute(
        ListAvailableMachinesQuery(
            role=bot_user.role,
            technician_id=bot_user.technician_id,
            scope=scope,
        ),
    )
