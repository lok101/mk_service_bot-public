from __future__ import annotations

from aiogram_dialog import DialogManager
from beartype import beartype

from src.application.form_workflow import (
    MaintenanceWorkflowScreen,
    utc_now,
)
from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import TechnicianId
from src.domain.system_user import SystemUser
from src.interfaces.telegram.form_workflow import FormWorkflowSession
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.machines.access import maintenance_state_for_bot_user
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.dialog_data import get_selected_machine_id
from src.interfaces.telegram.machines.state import MachineListState


@beartype
def _maintenance_screen_for_bot_user(bot_user: SystemUser | None) -> MaintenanceWorkflowScreen:
    state = maintenance_state_for_bot_user(bot_user)
    if state is MachineListState.admin_maintenance:
        return "admin_maintenance"
    return "maintenance"


async def register_form_workflow_session(
    session_store: FormWorkflowSessionStore,
    deps: MachineListDeps,
    *,
    chat_id: int,
    telegram_user_id: int,
    technician_id: TechnicianId,
    dialog_manager: DialogManager,
    purpose: FormSubmissionPurpose,
    dialog_message_id: int | None = None,
    bot_user: SystemUser | None = None,
) -> None:
    machine_id = get_selected_machine_id(dialog_manager)
    machine_name = dialog_manager.dialog_data.get("machine_name")
    if not isinstance(machine_name, str):
        machine_name = machine_id.value

    resolved_bot_user = bot_user
    if resolved_bot_user is None:
        resolved_bot_user = await resolve_bot_user(deps, telegram_user_id)
    maintenance_screen = _maintenance_screen_for_bot_user(resolved_bot_user)

    session_store.upsert(
        FormWorkflowSession(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            technician_id=technician_id,
            machine_id=machine_id,
            machine_name=machine_name,
            purpose=purpose,
            maintenance_screen=maintenance_screen,
            registered_at=utc_now(),
            dialog_message_id=dialog_message_id,
        ),
    )
