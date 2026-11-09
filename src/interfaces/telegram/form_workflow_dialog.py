from __future__ import annotations

import logging
from typing import cast

from aiogram_dialog import DialogManager
from aiogram_dialog.api.entities import ShowMode
from beartype import beartype

from src.interfaces.telegram.contracts import TelegramDialogBackgroundManager
from src.interfaces.telegram.form_workflow import FormWorkflowSession
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.workspace_links import provision_workspace_links

logger = logging.getLogger(__name__)


def _apply_session_to_dialog_data(
    manager: DialogManager,
    session: FormWorkflowSession,
    *,
    form_error: str | None,
) -> None:
    manager.dialog_data["machine_id"] = session.machine_id.value
    manager.dialog_data["machine_name"] = session.machine_name
    if form_error is not None:
        manager.dialog_data["form_workflow_error"] = form_error
    else:
        manager.dialog_data.pop("form_workflow_error", None)


@beartype
def _should_refresh_links(
    *,
    refresh_links: bool,
    form_error: str | None,
) -> bool:
    if refresh_links:
        return True
    return form_error is None


async def refresh_workspace_panel(
    bg: TelegramDialogBackgroundManager,
    deps: MachineListDeps,
    *,
    session: FormWorkflowSession,
    form_error: str | None = None,
    refresh_links: bool = False,
) -> bool:
    """Redraw workspace message. Returns False when no dialog context is open."""
    async with bg.fg() as manager:
        dialog_manager = cast(DialogManager, manager)
        if not dialog_manager.has_context():
            logger.warning(
                "Form workflow: no dialog context for telegram_user_id=%s chat_id=%s",
                session.telegram_user_id,
                session.chat_id,
            )
            return False

        _apply_session_to_dialog_data(
            dialog_manager,
            session,
            form_error=form_error,
        )

        if _should_refresh_links(refresh_links=refresh_links, form_error=form_error):
            message_id = session.dialog_message_id
            if message_id is None:
                stack = dialog_manager.current_stack()
                if stack is not None:
                    message_id = stack.last_message_id

            await provision_workspace_links(
                deps,
                manager=dialog_manager,
                chat_id=session.chat_id,
                telegram_user_id=session.telegram_user_id,
                technician_id=session.technician_id,
                machine_id=session.machine_id,
                dialog_message_id=message_id,
            )

        dialog_manager.show_mode = ShowMode.EDIT
        await dialog_manager.show(ShowMode.EDIT)
        return True
