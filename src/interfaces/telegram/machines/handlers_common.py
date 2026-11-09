from __future__ import annotations

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from beartype import BeartypeConf, beartype
from beartype._util.kind.maplike.utilmapfrozen import (
    FrozenDict,  # hashable hint_overrides for BeartypeConf
)

from src.application.machine_operations import (
    GetServiceCapabilitiesCommand,
    ServiceAction,
    blocked_service_action_reason,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import SystemUser
from src.interfaces.telegram.machines.access import (
    can_use_bot,
    technician_id_for_machine_operations,
)
from src.interfaces.telegram.machines.deps import MachineListDeps

_UNKNOWN_TECHNICIAN_ALERT = "Не удалось найти техника."
_UNKNOWN_USER_ALERT = "Не удалось найти пользователя."
_INACTIVE_USER_ALERT = "Ваша учётная запись неактивна. Обратитесь к администратору."


def _callback_chat_id(callback: CallbackQuery) -> int | None:
    if callback.message is None:
        return None
    return callback.message.chat.id


def _dialog_message_id(callback: CallbackQuery) -> int | None:
    if callback.message is None:
        return None
    return callback.message.message_id


HANDLERS_BEARTYPE_CONF = BeartypeConf(
    hint_overrides=FrozenDict({DialogManager: object}),
)


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class CommonHandlersMixin:
    deps: MachineListDeps

    async def _require_technician_id(
        self,
        callback: CallbackQuery,
        bot_user: SystemUser | None,
        machine_id: MachineId,
    ) -> TechnicianId | None:
        if bot_user is None:
            await callback.answer(_UNKNOWN_USER_ALERT, show_alert=True)
            return None
        if not can_use_bot(bot_user):
            await callback.answer(_INACTIVE_USER_ALERT, show_alert=True)
            return None

        technician_id = technician_id_for_machine_operations(bot_user)
        if technician_id is None:
            await callback.answer(_UNKNOWN_TECHNICIAN_ALERT, show_alert=True)
            return None

        return technician_id

    async def _answer_if_action_blocked(
        self,
        callback: CallbackQuery,
        *,
        bot_user: SystemUser | None,
        machine_id: MachineId,
        can_flag: bool,
        domain_reason: str,
        action: ServiceAction,
    ) -> bool:
        """Return True if action is allowed; otherwise answer alert and return False."""
        if can_flag:
            return True
        reason = domain_reason
        if not can_flag and bot_user is not None and can_use_bot(bot_user):
            technician_id = technician_id_for_machine_operations(bot_user)
            if technician_id is not None:
                caps = self.deps.get_service_capabilities.execute(
                    GetServiceCapabilitiesCommand(
                        technician_id=technician_id,
                        machine_id=machine_id,
                    ),
                )
                reason = blocked_service_action_reason(
                    action=action,
                    caps=caps,
                    cooldown_active=None,
                    maintenance_cooldown_minutes=self.deps.maintenance_cooldown_minutes,
                    default_reason=domain_reason,
                )
        await callback.answer(reason, show_alert=True)
        return False
