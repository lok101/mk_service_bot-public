from __future__ import annotations

from aiogram_dialog import DialogManager

from src.application.machine_operations import (
    CreateLoadingFormCommand,
    GetServiceCapabilitiesCommand,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import SystemUser
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.pending_registration import (
    register_form_workflow_session,
)

_REVISION_URL_KEY = "revision_form_url"
_LOADING_URL_KEY = "loading_form_url"
_MICROMARKET_INVENTORY_URL_KEY = "micromarket_inventory_form_url"
_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY = "micromarket_inventory_issue_error"


def _read_machine_name(dialog_manager: DialogManager, machine_id: MachineId) -> str:
    machine_name = dialog_manager.dialog_data.get("machine_name")
    if isinstance(machine_name, str) and machine_name:
        return machine_name
    return machine_id.value


async def provision_workspace_links(
    deps: MachineListDeps,
    *,
    manager: DialogManager,
    chat_id: int,
    telegram_user_id: int,
    technician_id: TechnicianId,
    machine_id: MachineId,
    dialog_message_id: int | None = None,
    bot_user: SystemUser | None = None,
) -> None:
    """Refresh form URLs and sessions from current ServiceCapabilities."""
    machine_name = _read_machine_name(manager, machine_id)
    manager.dialog_data["machine_id"] = machine_id.value
    manager.dialog_data["machine_name"] = machine_name

    resolved_bot_user = bot_user
    if resolved_bot_user is None:
        resolved_bot_user = await resolve_bot_user(deps, telegram_user_id)

    caps = deps.get_service_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=technician_id,
            machine_id=machine_id,
        ),
    )

    if caps.can_complete_revision and caps.revision_form_link is not None:
        manager.dialog_data[_REVISION_URL_KEY] = caps.revision_form_link.url
        await register_form_workflow_session(
            deps.form_workflow_sessions,
            deps,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            technician_id=technician_id,
            dialog_manager=manager,
            purpose="revision",
            dialog_message_id=dialog_message_id,
            bot_user=resolved_bot_user,
        )
    else:
        manager.dialog_data.pop(_REVISION_URL_KEY, None)
        deps.form_workflow_sessions.remove(
            technician_id,
            machine_id,
            "revision",
        )

    if caps.can_submit_loading:
        result = deps.create_loading_form.execute(
            CreateLoadingFormCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        manager.dialog_data[_LOADING_URL_KEY] = result.form_link.url
        await register_form_workflow_session(
            deps.form_workflow_sessions,
            deps,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            technician_id=technician_id,
            dialog_manager=manager,
            purpose="loading",
            dialog_message_id=dialog_message_id,
            bot_user=resolved_bot_user,
        )
    else:
        manager.dialog_data.pop(_LOADING_URL_KEY, None)
        deps.form_workflow_sessions.remove(
            technician_id,
            machine_id,
            "loading",
        )

    if caps.responsibility_phase == "responsible" and not caps.can_complete_revision:
        manager.dialog_data.pop(_REVISION_URL_KEY, None)
        deps.form_workflow_sessions.remove(
            technician_id,
            machine_id,
            "revision",
        )
