from __future__ import annotations

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.kbd import Button
from beartype import beartype

from src.application.machine_operations import (
    CompleteMaintenanceCommand,
    GetServiceCapabilitiesCommand,
)
from src.domain.machine_operations.events import MaintenanceCompleted
from src.domain.results import (
    MaintenanceAlreadyCompletedToday,
    MaintenanceCooldownActive,
    MaintenanceNotAllowed,
)
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.dialog_data import get_selected_machine_id
from src.interfaces.telegram.machines.handlers_common import (
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
)
from src.interfaces.telegram.machines.location_scope import (
    location_scope_from_manager,
    start_data_for_scope,
)
from src.interfaces.telegram.machines.state import MachineListState
from src.interfaces.telegram.machines.workspace_screen import stub_reason_for_action


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class MaintenanceHandlersMixin(CommonHandlersMixin):
    async def on_revision_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        caps = self.deps.get_service_capabilities.execute(
            GetServiceCapabilitiesCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        await self._answer_if_action_blocked(
            callback,
            bot_user=bot_user,
            machine_id=machine_id,
            can_flag=caps.can_complete_revision,
            domain_reason=stub_reason_for_action("revision"),
            action="revision",
        )

    async def on_loading_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        caps = self.deps.get_service_capabilities.execute(
            GetServiceCapabilitiesCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        await self._answer_if_action_blocked(
            callback,
            bot_user=bot_user,
            machine_id=machine_id,
            can_flag=caps.can_submit_loading,
            domain_reason=stub_reason_for_action("loading"),
            action="loading",
        )

    async def on_complete_maintenance_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        caps = self.deps.get_service_capabilities.execute(
            GetServiceCapabilitiesCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        await self._answer_if_action_blocked(
            callback,
            bot_user=bot_user,
            machine_id=machine_id,
            can_flag=caps.can_complete_maintenance,
            domain_reason=stub_reason_for_action("complete_maintenance"),
            action="complete_maintenance",
        )

    async def on_maintenance_completed(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return

        result = self.deps.complete_maintenance.execute(
            CompleteMaintenanceCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )

        if isinstance(result, MaintenanceAlreadyCompletedToday):
            await callback.answer(result.reason, show_alert=True)
            return

        if isinstance(result, MaintenanceNotAllowed):
            await callback.answer(result.reason, show_alert=True)
            return

        if isinstance(result, MaintenanceCooldownActive):
            await callback.answer(result.reason, show_alert=True)
            return

        if isinstance(result, MaintenanceCompleted):
            await callback.answer("Обслуживание завершено.")
            scope = location_scope_from_manager(manager)
            await manager.start(
                MachineListState.machines,
                mode=StartMode.RESET_STACK,
                data=start_data_for_scope(scope),
            )
            return

        await callback.answer("Не удалось завершить обслуживание.", show_alert=True)
